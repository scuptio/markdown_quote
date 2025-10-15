"""
A command line tool that processes markdown files to replace quote blocks with actual content from referenced files.

Inspired by Jetbrains MarkdownQuote plugin:
https://plugins.jetbrains.com/plugin/22311-markdownquote

This tool scans markdown files for special quote blocks in the format:
<!-- quote_begin content="[description](file_path#Lstart_line-Lend_line)" lang="language" -->
...existing content...
<!-- quote_end -->

And replaces them with the actual content from the referenced files.
"""

import os
import re
import glob
import argparse
from collections import deque, defaultdict


# Regular expression patterns for parsing quote blocks
CONTENT_PATTERN = r'\s+content="\[([\s\S]*?)\]\((?P<content>[\s\S]*?)\)"'
LANG_PATTERN = r'\s+lang="(?P<lang>.*?)"'
VALUES_PATTERN = rf'(({CONTENT_PATTERN})|({LANG_PATTERN}))*'
BEGIN_PATTERN = rf'<!--\s*quote_begin({VALUES_PATTERN})\s*-->'
END_PATTERN = r'<!--\s*quote_end\s*-->'
QUOTE_PATTERN = rf'(?P<begin_block>{BEGIN_PATTERN})([.\s\S]*)(?P<end_block>{END_PATTERN})'


def topological_sort(dependencies):
    """
    Perform topological sorting on dependency relationships using Kahn's algorithm.

    This ensures files are processed in the correct order based on their dependencies.
    If file A references file B, then file B should be processed before file A.

    Args:
        dependencies: Dictionary where key is a file path, value is a set of files that depend on the key
                    Format: {file_path: {dependent_file1, dependent_file2, ...}}
                    This means the key file must be processed before all files in the value set

    Returns:
        list: Files in topological order (files with no dependencies first),
              or empty list if a cycle is detected
    """
    # Build in-degree count and adjacency list
    in_degree = defaultdict(int)  # Tracks how many dependencies each file has
    graph = defaultdict(list)     # Maps files to their dependents

    # Collect all nodes from the dependency graph
    all_nodes = set()
    for key, dependents in dependencies.items():
        all_nodes.add(key)
        all_nodes.update(dependents)

    # Build the graph structure
    # If file A depends on file B, we have: B -> A (B must be processed before A)
    for key, dependents in dependencies.items():
        for dependent in dependents:
            graph[key].append(dependent)
            in_degree[dependent] += 1

    # Initialize queue with nodes having zero in-degree (no dependencies)
    queue = deque()
    for node in all_nodes:
        if in_degree[node] == 0:
            queue.append(node)

    # Perform topological sort using Kahn's algorithm
    result = []
    while queue:
        current_node = queue.popleft()
        result.append(current_node)

        # Process all nodes that depend on the current node
        for neighbor in graph.get(current_node, []):
            in_degree[neighbor] -= 1
            # If neighbor has no more dependencies, add to queue
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Check for cycles - if result doesn't include all nodes, a cycle exists
    if len(result) != len(all_nodes):
        print("Cycle detected in dependency graph")
        return []

    return result


def extract_line_range(file_path, start_line, end_line):
    """
    Extract content from specified line range in a file.

    Args:
        file_path: Path to the file to read
        start_line: Starting line number (1-based)
        end_line: Ending line number (1-based)

    Returns:
        str: Content from the specified line range, or None if error occurs
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Ensure line numbers are within valid range
        start_line = max(1, min(start_line, len(lines)))
        end_line = max(start_line, min(end_line, len(lines)))

        # Extract specified line range (convert to 0-based indexing)
        content_lines = lines[start_line - 1:end_line]
        return ''.join(content_lines)
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return None


def parse_path_spec(path_spec):
    """
    Parse path specification to extract file path and line range.

    Format example: "../../xxx.rs#L22-L34"

    Args:
        path_spec: Path specification string

    Returns:
        tuple: (file_path, start_line, end_line) or (None, None, None) if parsing fails
    """
    # Use regex to match path and line numbers
    match = re.match(r'(.+)#L(\d+)-L(\d+)', path_spec)
    if not match:
        return None, None, None

    file_path = match.group(1)
    start_line = int(match.group(2))
    end_line = int(match.group(3))

    return file_path, start_line, end_line


def process_parameters(match):
    """
    Extract parameter information from regex match.

    Args:
        match: Regex match object from quote pattern

    Returns:
        tuple: (file_path, start_line, end_line, language)
    """
    # Extract path information from content group
    content_block = match.group("content")
    file_path, start_line, end_line = parse_path_spec(content_block)

    # Extract language or default to "text"
    lang = match.group("lang")
    lang = lang if lang else "text"

    return file_path, start_line, end_line, lang


def to_full_path(file_path, md_file_dir):
    """
    Convert relative path to absolute path based on markdown file's directory.

    Args:
        file_path: Relative or absolute file path
        md_file_dir: Directory of the markdown file containing the reference

    Returns:
        str: Absolute file path
    """
    if os.path.isabs(file_path):
        return file_path
    else:
        return os.path.join(md_file_dir, file_path)


def process_quote_block(match, md_file_dir):
    """
    Process a single quote block and replace its content with referenced file content.

    Args:
        match: Regex match object for the quote block
        md_file_dir: Directory of the markdown file being processed

    Returns:
        str: New block content with referenced file content, or None if processing fails
    """
    quote_begin_block = match.group("begin_block")
    quote_end_block = match.group("end_block")

    # Extract path information from the match
    file_path, start_line, end_line, lang = process_parameters(match)

    if not file_path:
        return None

    # Convert to absolute path
    full_file_path = to_full_path(file_path, md_file_dir)

    # Read content from specified file and line range
    text_content = extract_line_range(full_file_path, start_line, end_line)
    if text_content is None:
        return None

    # Format the content based on language
    if lang != "text":
        # For source code, create a code block with language specification
        new_code_block = f"```{lang}\n{text_content}```"
    else:
        # For non-code content, output directly
        new_code_block = f"\n{text_content}"

    # Rebuild the block with new content
    new_block = f'{quote_begin_block}\n{new_code_block}\n{quote_end_block}'

    return new_block


def normalized_path(file_path):
    """
    Normalize file path to absolute and standardized format.

    Args:
        file_path: Input file path

    Returns:
        str: Normalized absolute path
    """
    abs_path = os.path.abspath(file_path)
    return os.path.normpath(abs_path)


def pre_process_md_file(md_file_path, dependency_map):
    """
    Pre-process a markdown file to build dependency relationships.

    This function scans for quote blocks and records which files depend on which other files.

    Args:
        md_file_path: Path to the markdown file to pre-process
        dependency_map: Dictionary to update with dependency information
    """
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        md_file_dir = os.path.dirname(md_file_path)

        # Find all quote blocks in the file
        match_list = re.finditer(QUOTE_PATTERN, content, flags=re.DOTALL)

        # Get normalized path of current file
        this_file_normalized = normalized_path(md_file_path)

        # Process each quote block to extract dependencies
        for match in match_list:
            file_path, _start_line, _end_line, _ = process_parameters(match)
            full_file_path = to_full_path(file_path, md_file_dir)
            depend_file_normalized = normalized_path(full_file_path)

            # Add dependency relationship: depend_file -> this_file
            # Meaning: depend_file must be processed before this_file
            if depend_file_normalized not in dependency_map:
                dependency_map[depend_file_normalized] = {this_file_normalized}
            else:
                dependency_map[depend_file_normalized].add(this_file_normalized)

    except Exception as e:
        print(f"Error pre-processing file {md_file_path}: {e}")


def process_md_file(md_file_path):
    """
    Process a single markdown file, replacing quote blocks with actual content.

    Args:
        md_file_path: Path to the markdown file to process
    """
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        md_file_dir = os.path.dirname(md_file_path)

        # Replace all quote blocks with actual content
        new_content = re.sub(
            QUOTE_PATTERN,
            lambda match: process_quote_block(match, md_file_dir),
            content,
            flags=re.DOTALL
        )

        # Write back to file only if content changed
        if new_content != content:
            with open(md_file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated quotes in: {md_file_path}")

    except Exception as e:
        print(f"Error processing file {md_file_path}: {e}")


def is_md_file(filename):
    """
    Check if a file is a markdown file based on extension.

    Args:
        filename: File name or path to check

    Returns:
        bool: True if file has .md extension (case-insensitive)
    """
    _, ext = os.path.splitext(filename)
    return ext.lower() == '.md'


def main():
    """
    Main function: Process all .md files in specified directory with dependency resolution.

    The process involves two passes:
    1. Pre-processing: Build dependency graph between files
    2. Processing: Process files in topological order based on dependencies
    """

    parser = argparse.ArgumentParser(description="markdown_quote processes markdown files to replace quote blocks with actual content from referenced files.")
    parser.add_argument('--version', action='version', version='0.0.1')
    parser.add_argument('--input', help="Input folder path to scan")

      # Directory to scan for markdown files
    args = parser.parse_args()
    folder_path = args.input
    if folder_path is None:
        folder_path = '.'

    if not os.path.exists(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist")
        return

    # Find all .md files recursively
    md_files = glob.glob(os.path.join(folder_path, "**/*.md"), recursive=True)

    if not md_files:
        print("No markdown files found")
        return

    n = len(md_files)
    print(f"Found {n} markdown files")

    # First pass: Build dependency map
    dep_map = {}
    for md_file in md_files:
        pre_process_md_file(md_file, dep_map)

    # Sort files based on dependencies (files with no dependencies first)
    sorted_files = topological_sort(dep_map)

    # Second pass: Process files in dependency order
    for file_path in sorted_files:
        if is_md_file(file_path):
            process_md_file(file_path)

    print("Quote processing completed")


if __name__ == "__main__":
    main()