from swebench.harness.test_spec.utils import make_eval_script_list_common


def test_common_eval_reset_runs_from_repo_root_after_cd_test_command():
    script = make_eval_script_list_common(
        instance={"repo": "openmm/openmm", "version": "5155"},
        specs={},
        env_name="testbed",
        repo_directory="/testbed",
        base_commit="abc123",
        test_patch="""diff --git a/wrappers/python/tests/TestGromacsTopFile.py b/wrappers/python/tests/TestGromacsTopFile.py
--- a/wrappers/python/tests/TestGromacsTopFile.py
+++ b/wrappers/python/tests/TestGromacsTopFile.py
@@ -1 +1,2 @@
 pass
+def test_example(): pass
""",
    )

    reset_commands = [
        cmd
        for cmd in script
        if "git checkout abc123 wrappers/python/tests/TestGromacsTopFile.py" in cmd
    ]

    assert reset_commands == [
        "cd /testbed && git checkout abc123 wrappers/python/tests/TestGromacsTopFile.py",
        "cd /testbed && git checkout abc123 wrappers/python/tests/TestGromacsTopFile.py",
    ]
