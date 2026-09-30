#!/usr/bin/env python3
"""Natural Language Cell Creation via Gemini API.

Takes a plain English description and generates a governance cell with
proper YAML frontmatter, hypothesis, prediction, and falsification.
"""
import os, sys, argparse, json, subprocess
from soma_resolve import resolve_workspace
from inference_provider import resolve_provider

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None

def create_cell_from_description(description, domain_hint=None, cell_type=None, provider_name=None):
    """Use AI to generate cell YAML from natural language."""
    workspace = resolve_workspace(__file__)
    
    provider = resolve_provider(workspace, provider_name)
    
    # Load existing cells as examples
    import glob, yaml
    examples = []
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if os.path.isdir(cells_dir):
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md': continue
            try:
                with open(cell_file, encoding="utf-8") as f:
                    content = f.read()
                if content.startswith('---'):
                    examples.append(content[:500])  # Truncate for context
            except Exception: pass
    
    example_text = '\n---\n'.join(examples[:3]) if examples else 'No existing cells found.'
    
    domain_context = f'\nDomain hint: {domain_hint}' if domain_hint else ''
    type_hint = f'\nPreferred cell type: {cell_type}' if cell_type else ''
    
    prompt = f"""You are a governance cell generator for Soma.

Given a natural language description of a concern, generate a governance cell in markdown with YAML frontmatter.

Cell types:
- wall: Non-negotiable invariant (hard safety gate). Use for things that must ALWAYS hold.
- vacuole: Learned anti-pattern trap. Use for known failure modes to watch for.
- membrane: Escalation gate. Use when sensitive areas need elevated review.
- chloroplast: Domain persona/accelerator. Use for idiomatic patterns to follow.
- plasmodesmata: Cross-service contract. Use for API/data shape agreements.

YAML fields required:
- type: (one of above)
- hypothesis: (clear, testable statement)
- prediction: (what will happen if the hypothesis is violated)
- falsification: (how to prove this cell is no longer needed)
- target_paths: (list of file glob patterns this cell monitors)
- minimum_mode: (breeze | gale | trident | maelstrom | tempest)
- tags: (list of relevant tags)

Optionally include:
- fitness: (triggers: 0, true_positives: 0, false_positives: 0, score: null)

Existing cells in this project for reference:
{example_text}
{domain_context}{type_hint}

User description: "{description}"

Generate ONLY the complete markdown cell file content. Start with --- for the YAML frontmatter. After the closing ---, include a brief description paragraph explaining the cell's purpose. Do not include any other text."""
    
    response_text = provider.generate(prompt)
    
    return response_text.strip()


def create_cell_from_insight_cluster(cluster: dict, workspace: str) -> str:
    """Create a governance cell from an insight cluster.

    Parameters
    ----------
    cluster : dict
        A cluster dict produced by :func:`enzymes.insight_correlator.cluster_insights`.
        Expected keys: ``common_category``, ``common_files``, ``confidence``.
    workspace : str
        Root of the Soma workspace.

    Returns
    -------
    str
        Absolute path to the newly created cell file.
    """
    import re

    category = cluster.get("common_category") or "unknown"
    files = cluster.get("common_files", [])
    confidence = cluster.get("confidence", 0.5)
    files_str = ", ".join(files) if files else "project-wide"

    hypothesis = f"Human attention pattern detected: {category} in {files_str}"

    frontmatter = {
        "type": "vacuole",
        "hypothesis": hypothesis,
        "prediction": f"Recurring {category} issues will continue if unaddressed",
        "falsification": f"No {category} insights observed for 60 days",
        "target_paths": list(files),
        "minimum_mode": "breeze",
        "origin": "human_insight",
        "tags": ["auto-generated", "insight-cluster", category],
        "fitness": {
            "triggers": 0,
            "true_positives": 0,
            "false_positives": 0,
            "score": None,
        },
    }

    # Build YAML frontmatter — works with or without pyyaml
    if _yaml is not None:
        fm_text = _yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    else:
        # Minimal manual serialisation for the known shape
        lines = []
        for key, value in frontmatter.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
            elif isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"{key}: {value}")
        fm_text = "\n".join(lines) + "\n"

    body = f"This vacuole was auto-generated from a cluster of human insights " \
           f"about **{category}** (confidence {confidence:.2f}).\n"

    cell_content = f"---\n{fm_text}---\n\n{body}"

    # Determine filename
    slug = re.sub(r"[^a-z0-9]+", "-", category.lower())[:50].strip("-") or "unknown"
    filename = f"vacuole-{slug}.md"

    target_dir = os.path.join(workspace, ".soma", "cells", "vacuoles")
    os.makedirs(target_dir, exist_ok=True)

    filepath = os.path.join(target_dir, filename)

    # Collision safety: preserve existing cell fitness metadata
    if os.path.isfile(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                existing = f.read()
            if '---' in existing:
                end = existing.find('---', 3)
                if end != -1:
                    fm_text_existing = existing[3:end].strip()
                    if _yaml is not None:
                        existing_fm = _yaml.safe_load(fm_text_existing) or {}
                    else:
                        existing_fm = {}
                    existing_fitness = existing_fm.get('fitness')
                    if existing_fitness and isinstance(existing_fitness, dict):
                        if existing_fitness.get('triggers', 0) > 0:
                            # Cell has accumulated fitness data — don't overwrite
                            return filepath
        except Exception:
            pass

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(cell_content)

    return filepath


def main():
    parser = argparse.ArgumentParser(
        description='Create governance cells from natural language descriptions'
    )
    parser.add_argument('description', nargs='?', default=None,
                       help='Natural language description of the governance concern')
    parser.add_argument('--domain', help='Domain hint (e.g., rl, web, infra, data)')
    parser.add_argument('--type', choices=['wall', 'vacuole', 'membrane', 'chloroplast', 'plasmodesmata'],
                       help='Preferred cell type')
    parser.add_argument('--provider', choices=['auto', 'gemini', 'anthropic', 'openai', 'prompt-only'], default='auto',
                       help='Inference provider to use')
    parser.add_argument('--id', help='Short ID for the cell filename')
    parser.add_argument('--dry-run', action='store_true', help='Print generated cell without creating file')
    parser.add_argument('--json', action='store_true', help='Output metadata as JSON')
    parser.add_argument('--from-insight-cluster', action='store_true',
                       help='Create cells from insight clusters instead of AI generation')
    args = parser.parse_args()
    
    if args.from_insight_cluster:
        try:
            from enzymes.insight_correlator import cluster_insights
        except ImportError:
            from insight_correlator import cluster_insights
        workspace = resolve_workspace(__file__)
        clusters = cluster_insights(workspace)
        if not clusters:
            print('No insight clusters found.')
            return
        for cluster in clusters:
            path = create_cell_from_insight_cluster(cluster, workspace)
            print(f'✅ Created from cluster: {os.path.relpath(path, workspace)}')
        return

    if not args.description:
        parser.error('description is required unless --from-insight-cluster is used')

    print(f'🧬 Generating cell from description...')
    
    provider_name = None if args.provider == 'auto' else args.provider
    cell_content = create_cell_from_description(
        args.description,
        domain_hint=args.domain,
        cell_type=args.type,
        provider_name=provider_name
    )
    
    if args.dry_run:
        print('\n--- Generated Cell ---')
        print(cell_content)
        return
    
    # Parse the generated YAML to determine type and create filename
    import yaml
    try:
        if cell_content.startswith('```'):
            # Strip markdown code fences if present
            cell_content = cell_content.split('\n', 1)[1]
            if cell_content.rstrip().endswith('```'):
                cell_content = cell_content.rstrip()[:-3].rstrip()
        
        if cell_content.startswith('---'):
            yaml_block = cell_content[3:cell_content.find('---', 3)]
            fm = yaml.safe_load(yaml_block)
        else:
            print('Warning: Could not parse generated YAML frontmatter')
            fm = {}
    except Exception as e:
        print(f'Warning: YAML parse error: {e}')
        fm = {}
    
    cell_type = fm.get('type', 'vacuole')
    hypothesis = fm.get('hypothesis', args.description)
    
    # Generate filename
    if args.id:
        slug = args.id
    else:
        # Create slug from hypothesis
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', hypothesis.lower())[:50].strip('-')
    
    filename = f'{cell_type}-{slug}.md' if not slug.startswith(cell_type) else f'{slug}.md'
    
    # Determine target directory
    workspace = resolve_workspace(__file__)
    type_dirs = {
        'wall': 'walls', 'membrane': 'membranes', 'vacuole': 'vacuoles',
        'chloroplast': 'chloroplasts', 'plasmodesmata': 'plasmodesmata'
    }
    target_dir = os.path.join(workspace, '.soma', 'cells', type_dirs.get(cell_type, 'vacuoles'))
    os.makedirs(target_dir, exist_ok=True)
    
    filepath = os.path.join(target_dir, filename)
    
    with open(filepath, 'w', encoding="utf-8") as f:
        f.write(cell_content)
    
    rel_path = os.path.relpath(filepath, workspace)
    print(f'✅ Created: {rel_path}')
    print(f'   Type: {cell_type}')
    print(f'   Hypothesis: {hypothesis[:80]}')
    
    if args.json:
        print(json.dumps({
            'path': rel_path,
            'type': cell_type,
            'hypothesis': hypothesis,
            'filename': filename
        }, indent=2))


if __name__ == '__main__':
    main()
