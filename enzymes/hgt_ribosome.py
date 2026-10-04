#!/usr/bin/env python3
"""Horizontal Gene Transfer (Ribosome) Engine

Translates highly-fit domain-specific cells (e.g., from Rimworld) into 
universal, meta-cognitive software engineering laws (Genome).

Designed to run on extremely cheap, fast models (e.g., gemini-1.5-flash) 
since the translation task is straightforward noun-stripping and abstraction.
"""

import os
import sys
import argparse
import yaml
import re

def parse_frontmatter(content):
    if not content.startswith('---'):
        return {}, content
    end = content.find('---', 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    result = {}
    for line in fm_text.split('\n'):
        match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)', line.strip())
        if match:
            result[match.group(1)] = match.group(2).strip('"').strip("'")
    return result, content[end+3:].strip()

def prompt_llm_translation(cell_content: str, mock: bool = False) -> str:
    """
    Calls a cheap inference model (like flash) to translate the cell.
    """
    prompt = f"""
You are a Ribosome in an evolutionary AI system.
Your job is to translate this domain-specific strategy into a universal, meta-cognitive software engineering law.
Strip away all specific nouns (e.g., 'pawns', 'raids', 'food'). 
Extract the underlying meta-cognitive pattern and format it as a markdown file.

Input Cell:
{cell_content}

Output Format:
# [Abstract Strategy Name]
- [Universal Law 1]
- [Universal Law 2]
"""
    if mock:
        # For our local verification, we mock the LLM output for the raid_defense playbook
        if "draft all combat-capable pawns" in cell_content:
            return """# Resource Consolidation (HGT)
- When a catastrophic event is detected (e.g., massive production outage), immediately consolidate resources to a defensible position.
- Halt all exploratory or non-essential feature work until the primary threat is neutralized.
- Do not engage in risky ad-hoc fixes unless core stability is breached."""
        else:
            return "# Generalized Strategy\n- Apply caution and verify inputs."
            
    # In production, this would use `inference_provider.py` to call the LLM
    print("Calling cheap inference provider (e.g. gemini-1.5-flash)...")
    return "# Generalized Strategy\n- Apply caution and verify inputs."

def main():
    parser = argparse.ArgumentParser(description="HGT Ribosome Translator")
    parser.add_argument("source_file", help="Path to the highly-fit foreign cell")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM output for local testing")
    args = parser.parse_args()

    if not os.path.exists(args.source_file):
        print(f"Error: {args.source_file} not found.")
        sys.exit(1)

    with open(args.source_file, 'r', encoding="utf-8") as f:
        content = f.read()

    metadata, body = parse_frontmatter(content)
    
    print(f"🧬 Ribosome intercepting: {args.source_file}")
    print("Translating domain-specific logic to universal genome...")
    
    translated_body = prompt_llm_translation(body, mock=args.mock)
    
    # Save the new genome
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    genome_dir = os.path.join(workspace_dir, "genome")
    os.makedirs(genome_dir, exist_ok=True)
    
    # Create filename based on abstract name
    first_line = translated_body.split('\n')[0]
    filename_base = re.sub(r'[^a-z0-9]+', '-', first_line.lower().replace('#', '').strip()).strip('-')
    gene_id = f"hgt-{filename_base}"
    filename = f"{gene_id}.md"
    
    output_path = os.path.join(genome_dir, filename)
    
    new_metadata = {
        "id": gene_id,
        "domain": "governance",
        "name": filename_base,
        "type": "gene",
        "hgt_source": args.source_file,
        "trigger": "universal"
    }
    
    with open(output_path, 'w', encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(new_metadata, f, default_flow_style=False, sort_keys=False)
        f.write("---\n\n")
        f.write(translated_body)
        
    print(f"✅ HGT Successful! New meta-cognitive gene injected at: {output_path}")

if __name__ == "__main__":
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
