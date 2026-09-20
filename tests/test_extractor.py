from vibecheck.extractor import extract_rules, extract_rules_from_text, find_agents_md
from vibecheck.models import RuleCategory, RuleType


def ids(rules):
    return {r.id for r in rules}


def by_id(rules):
    return {r.id: r for r in rules}


def test_extract_minimal(fixtures_dir):
    rules = extract_rules(fixtures_dir / "minimal" / "AGENTS.md")
    assert ids(rules) == {
        "meta_agents_md",
        "build_uv",
        "test_unit_dir",
        "arch_makefile",
        "qual_ruff",
        "sec_no_secrets",
    }
    r = by_id(rules)
    assert r["build_uv"].category == RuleCategory.BUILD
    assert r["test_unit_dir"].category == RuleCategory.TESTING
    assert r["arch_makefile"].category == RuleCategory.ARCHITECTURE
    assert r["qual_ruff"].category == RuleCategory.CODE_QUALITY
    assert r["sec_no_secrets"].category == RuleCategory.SECURITY
    assert r["meta_agents_md"].weight == 2.0


def test_extract_fastapi(fixtures_dir):
    found = ids(extract_rules(fixtures_dir / "fastapi" / "AGENTS.md"))
    expected = {
        "build_uv", "build_no_pip", "arch_layered", "arch_di", "arch_api_versioning",
        "arch_async", "arch_pydantic_settings", "arch_alembic", "arch_makefile",
        "arch_docker", "arch_openapi", "sec_auth", "sec_password_hashing", "sec_rbac",
        "sec_no_secrets", "sec_env_gitignore", "test_unit_dir", "test_integration_dir",
        "test_bdd", "test_conftest", "test_no_skip", "qual_ruff", "qual_mypy",
        "qual_sqlalchemy_mapped", "qual_pydantic_v2", "spec_dir", "spec_adr",
        "spec_conventional_commits",
    }  # fmt: skip
    assert expected <= found


def test_extract_java(fixtures_dir):
    found = ids(extract_rules(fixtures_dir / "java" / "AGENTS.md"))
    assert {"build_maven", "arch_jpms", "arch_hexagonal", "arch_di", "test_component",
            "test_bdd", "qual_checkstyle", "qual_spotbugs", "sec_auth"} <= found  # fmt: skip


def test_extract_no_rules(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("")
    rules = extract_rules(p)
    assert ids(rules) == {"meta_agents_md"}


def test_extract_deduplication():
    text = "We use uv here.\n\n## More\n\nAlways uses uv, really. Uses uv!\n"
    rules = extract_rules_from_text(text)
    assert [r.id for r in rules].count("build_uv") == 1


def test_extract_source_text_and_first_wins():
    rules = by_id(extract_rules_from_text("Project uses uv.\n\n## X\n\nAlso using uv.\n"))
    assert rules["build_uv"].source_text == "Project uses uv."


def test_extract_tree_parsing():
    text = """# Layout

```
├── src/
│   ├── services/
│   └── models/
├── tests/
└── Makefile
```
"""
    rules = by_id(extract_rules_from_text(text))
    for rid, path in {
        "struct_src": "src",
        "struct_src_services": "src/services",
        "struct_src_models": "src/models",
        "struct_tests": "tests",
        "struct_makefile": "Makefile",
    }.items():
        assert rules[rid].rule_type == RuleType.FILE_EXISTS
        assert rules[rid].check_params["path"] == path
        assert rules[rid].weight == 0.5


def test_extract_tree_with_root_marker_and_comments():
    text = """```
vibecheck/
├── pyproject.toml   # packaging
├── src/
│   └── vibecheck/
│       └── cli.py   # CLI entry point
└── README.md
```
"""
    rules = by_id(extract_rules_from_text(text))
    assert rules["struct_src_vibecheck_cli_py"].check_params["path"] == "src/vibecheck/cli.py"
    assert rules["struct_pyproject_toml"].check_params["path"] == "pyproject.toml"
    assert "struct_readme_md" in rules
    assert not any(i.startswith("struct_vibecheck") for i in rules)


def test_extract_tree_noise_filtering():
    text = """```
├── src/
│   ├── Some comment about the layout
│   ├── The
│   ├── a
│   ├── ...
│   └── real_module.py
├── tests/
└── Notes
```
"""
    found = ids(extract_rules_from_text(text))
    assert "struct_src_real_module_py" in found
    assert "struct_src_some_comment_about_the_layout" not in found
    assert not any("the" == i.rsplit("_", 1)[-1] and i.startswith("struct_src_") for i in found)
    assert "struct_notes" not in found  # uppercase, no dot/slash: treated as a comment
    assert "struct_src_a" not in found  # shorter than 2 chars
    assert not any("..." in i or i == "struct_src_" for i in found)


def test_tree_rejects_path_traversal():
    found = ids(extract_rules_from_text("```\n├── ../../etc/passwd\n└── ok.txt\n```\n"))
    assert "struct_ok_txt" in found
    assert not any("passwd" in i for i in found)


def test_tree_block_not_scanned_as_prose():
    # "docker" only appears inside a tree comment-free block entry; keywords in
    # trees must not produce keyword rules.
    text = "```\n├── docker/\n└── x.py\n```\n"
    found = ids(extract_rules_from_text(text))
    assert "arch_docker" not in found
    assert "struct_docker" in found


def test_heading_inside_code_fence_is_not_a_section():
    text = "```\n## uses uv\n```\n"
    assert "build_uv" in ids(extract_rules_from_text(text))


def test_no_pip_and_pip_negation_variants():
    assert "build_no_pip" in ids(extract_rules_from_text("Use uv (NOT pip)."))
    assert "build_no_pip" in ids(extract_rules_from_text("Never use pip."))
    assert "build_no_pip" not in ids(extract_rules_from_text("Install with pip install foo."))


def test_large_file_is_fast(tmp_path):
    import time

    p = tmp_path / "AGENTS.md"
    p.write_text("\n".join(f"Line {i} about async services and uses uv" for i in range(2000)))
    start = time.perf_counter()
    extract_rules(p)
    assert time.perf_counter() - start < 1.0


def test_find_agents_md(tmp_path):
    assert find_agents_md(tmp_path) is None
    (tmp_path / "CLAUDE.md").write_text("x")
    assert find_agents_md(tmp_path).name == "CLAUDE.md"
    (tmp_path / "AGENTS.md").write_text("x")
    assert find_agents_md(tmp_path).name == "AGENTS.md"
