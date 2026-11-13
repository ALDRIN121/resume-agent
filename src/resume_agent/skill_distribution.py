"""Export the same portable skill from a checkout or installed wheel."""
from pathlib import Path

FILES = ('SKILL.md', 'references/protocol.md', 'agents/openai.yaml')


def skill_source():
    packaged = Path(__file__).resolve().parent / '_skills' / 'resume-agent'
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2] / 'skills' / 'resume-agent'


def export_skill(destination):
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Skill destination already exists. Choose a new directory; existing files were retained.')
    source = skill_source()
    # Read only the shipped allowlist before creating a destination.
    files = {name: (source / name).read_bytes() for name in FILES}
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    return destination.resolve()
