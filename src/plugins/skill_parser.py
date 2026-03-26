"""
Skill package parser for .zip and .skill files.

Parses SKILL.md metadata and extracts skill packages.
"""

import yaml
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, Any, cast
from uuid import uuid4

from ..core.models import SkillPackageMetadata, InstalledSkill

logger = logging.getLogger(__name__)


class SkillParser:
    """
    Parser for skill packages (.zip or .skill files).

    Expected structure:
    skill-package.zip/
    ├── SKILL.md          # Metadata (YAML frontmatter)
    ├── skill.py          # Main skill code
    ├── requirements.txt  # Optional dependencies
    └── README.md         # Optional documentation
    """

    def __init__(self, skills_dir: str = "data/skills"):
        """
        Initialize skill parser.

        Args:
            skills_dir: Directory to store extracted skills
        """
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def parse_skill_package(self, file_path: str) -> InstalledSkill:
        """
        Parse a skill package from .zip or .skill file.

        Args:
            file_path: Path to the skill package file

        Returns:
            InstalledSkill object with metadata and package path

        Raises:
            ValueError: If SKILL.md is missing or invalid
        """
        # Create temporary directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract package
            self._extract_package(file_path, temp_dir)

            package_root = self._find_package_root(temp_dir)

            # Parse SKILL.md
            metadata = self._parse_skill_md(package_root)

            # Generate unique skill ID
            skill_id = str(uuid4())

            # Create permanent directory for this skill
            skill_dir = self.skills_dir / skill_id
            skill_dir.mkdir(parents=True, exist_ok=True)

            # Copy files to permanent location
            self._copy_skill_files(package_root, str(skill_dir))

            # Create InstalledSkill object
            installed_skill = InstalledSkill(
                id=skill_id,
                metadata=metadata,
                package_path=str(skill_dir),
            )

            logger.info(f"Installed skill: {metadata.name} (ID: {skill_id})")
            return installed_skill

    def _find_package_root(self, extracted_dir: str) -> str:
        root = Path(extracted_dir)
        if (root / "SKILL.md").exists():
            return str(root)

        candidates = list(root.glob("*/SKILL.md"))
        if len(candidates) == 1:
            return str(candidates[0].parent)

        if len(candidates) > 1:
            parents = ", ".join(sorted({c.parent.name for c in candidates}))
            raise ValueError(f"Multiple SKILL.md found in package: {parents}")

        raise ValueError("SKILL.md not found in package root (or a single top-level folder)")

    def _extract_package(self, file_path: str, extract_to: str) -> None:
        """
        Extract .zip or .skill file.

        Args:
            file_path: Path to the package file
            extract_to: Directory to extract to
        """
        file_path_obj = cast(Any, Path(file_path))

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Skill package not found: {file_path_obj}")

        # Both .zip and .skill are treated as zip archives
        if file_path_obj.suffix in ['.zip', '.skill']:
            with zipfile.ZipFile(file_path_obj, 'r') as zip_ref:
                # Security: prevent zip slip vulnerability
                for member in zip_ref.namelist():
                    member_path = Path(extract_to) / member
                    if not member_path.resolve().is_relative_to(Path(extract_to).resolve()):
                        raise ValueError(f"Invalid zip member path: {member}")

                zip_ref.extractall(extract_to)
        else:
            raise ValueError(f"Unsupported file type: {file_path_obj.suffix}")

    def _parse_skill_md(self, skill_dir: str) -> SkillPackageMetadata:
        """
        Parse SKILL.md file to extract metadata.

        Expected format:
        ---
        name: My Skill
        description: Does something useful
        version: 1.0.0
        author: John Doe
        tags: [productivity, automation]
        entry_point: skill.py
        function_name: execute
        approval_required: false
        dependencies:
          - requests
          - beautifulsoup4
        ---

        # Skill Documentation
        Additional markdown content...

        Args:
            skill_dir: Directory containing SKILL.md

        Returns:
            SkillPackageMetadata object
        """
        skill_md_path = Path(skill_dir) / "SKILL.md"

        if not skill_md_path.exists():
            raise ValueError("SKILL.md not found in package root")

        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract YAML frontmatter
        if not content.startswith('---'):
            raise ValueError("SKILL.md must start with YAML frontmatter (---)")

        # Find the end of frontmatter
        parts = content.split('---', 2)
        if len(parts) < 3:
            raise ValueError("SKILL.md frontmatter not properly closed with ---")

        yaml_content = parts[1].strip()

        try:
            metadata_dict = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in SKILL.md: {e}")

        # Validate required fields
        if 'name' not in metadata_dict:
            raise ValueError("SKILL.md must contain 'name' field")
        if 'description' not in metadata_dict:
            raise ValueError("SKILL.md must contain 'description' field")

        # Create metadata object
        metadata = SkillPackageMetadata(
            name=metadata_dict['name'],
            description=metadata_dict['description'],
            version=metadata_dict.get('version', '1.0.0'),
            author=metadata_dict.get('author'),
            tags=metadata_dict.get('tags', []),
            entry_point=metadata_dict.get('entry_point', 'skill.py'),
            function_name=metadata_dict.get('function_name', 'execute'),
            parameters_schema=metadata_dict.get('parameters_schema'),
            approval_required=metadata_dict.get('approval_required', False),
            dependencies=metadata_dict.get('dependencies', []),
            icon=metadata_dict.get('icon'),
        )

        return metadata

    def _copy_skill_files(self, source_dir: str, dest_dir: str) -> None:
        """
        Copy skill files to permanent location.

        Args:
            source_dir: Source directory (temp)
            dest_dir: Destination directory (permanent)
        """
        for item in Path(source_dir).iterdir():
            if item.is_file():
                shutil.copy2(item, dest_dir)
            elif item.is_dir():
                shutil.copytree(item, Path(dest_dir) / item.name, dirs_exist_ok=True)

    def uninstall_skill(self, skill_id: str) -> bool:
        """
        Remove an installed skill package.

        Args:
            skill_id: ID of the skill to remove

        Returns:
            True if successful, False if skill not found
        """
        skill_dir = self.skills_dir / skill_id

        if not skill_dir.exists():
            logger.warning(f"Skill directory not found: {skill_id}")
            return False

        try:
            shutil.rmtree(skill_dir)
            logger.info(f"Uninstalled skill: {skill_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to uninstall skill {skill_id}: {e}")
            return False

    def get_skill_file_path(self, skill_id: str, filename: str) -> Optional[str]:
        """
        Get path to a file within a skill package.

        Args:
            skill_id: Skill ID
            filename: File name within the package

        Returns:
            Full path to the file, or None if not found
        """
        file_path = self.skills_dir / skill_id / filename

        if file_path.exists():
            return str(file_path)

        return None


# Global parser instance
_skill_parser: Optional[SkillParser] = None


def get_skill_parser() -> SkillParser:
    """Get the global skill parser instance."""
    global _skill_parser
    if _skill_parser is None:
        _skill_parser = SkillParser()
    return _skill_parser
