from swebench.eval_pipeline.inference import _strip_generated_artifact_diff_blocks


def test_strip_generated_artifacts_keeps_authored_test_diff():
    patch = """diff --git a/tests/test_model.py b/tests/test_model.py
--- a/tests/test_model.py
+++ b/tests/test_model.py
@@ -1 +1,2 @@
 old
+new
diff --git a/tests/__pycache__/test_model.cpython-312.pyc b/tests/__pycache__/test_model.cpython-312.pyc
new file mode 100644
GIT binary patch
literal 3
abc
diff --git a/build-regression/result.txt b/build-regression/result.txt
new file mode 100644
--- /dev/null
+++ b/build-regression/result.txt
@@ -0,0 +1 @@
+generated
"""

    filtered = _strip_generated_artifact_diff_blocks(patch)

    assert "diff --git a/tests/test_model.py b/tests/test_model.py" in filtered
    assert "__pycache__" not in filtered
    assert "build-regression" not in filtered
