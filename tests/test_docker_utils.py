import urllib3.response

from swebench.harness.docker_utils import exec_run_with_timeout


def test_urllib3_closed_file_close_error_is_suppressed():
    from swebench.harness.docker_utils import patch_urllib3_closed_file_close_error

    patch_urllib3_closed_file_close_error()

    class ClosedFile:
        closed = False

        def close(self):
            raise ValueError("I/O operation on closed file.")

    response = urllib3.response.HTTPResponse(body="")
    response._fp = ClosedFile()

    response.close()


def test_urllib3_other_close_value_errors_still_raise():
    from swebench.harness.docker_utils import patch_urllib3_closed_file_close_error

    patch_urllib3_closed_file_close_error()

    class BadFile:
        closed = False

        def close(self):
            raise ValueError("different close failure")

    response = urllib3.response.HTTPResponse(body="")
    response._fp = BadFile()

    try:
        response.close()
    except ValueError as exc:
        assert "different close failure" in str(exc)
    else:
        raise AssertionError("expected non-closed-file ValueError to propagate")


def test_exec_run_with_timeout_replaces_non_utf8_output():
    class API:
        def exec_create(self, _container_id, _cmd):
            return {"Id": "exec-id"}

        def exec_start(self, _exec_id, stream=True):
            assert stream is True
            return iter([b"before\x80after"])

    class Client:
        api = API()

    class Container:
        id = "container-id"
        client = Client()

    output, timed_out, _runtime = exec_run_with_timeout(Container(), "cmd", 1)

    assert output == "before\ufffdafter"
    assert timed_out is False
