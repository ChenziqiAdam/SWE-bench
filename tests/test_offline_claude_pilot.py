

def test_claude_command_enables_sandboxed_bash_by_default(monkeypatch):
    import json

    from swebench.issue_pipeline.offline_claude_pilot import claude_command

    monkeypatch.delenv("SWEBENCH_CLAUDE_SANDBOX", raising=False)
    command = claude_command()
    settings = json.loads(command[command.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["autoAllowBashIfSandboxed"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    # prompts become denials in -p mode; the OS sandbox is what limits Bash
    assert command[command.index("--allowedTools") + 1] == "Bash"
    monkeypatch.setenv("SWEBENCH_CLAUDE_SANDBOX", "0")
    assert "--settings" not in claude_command()
    assert "--allowedTools" not in claude_command()


def test_overloaded_529_result_is_retryable():
    import json

    from swebench.issue_pipeline.offline_claude_pilot import detect_rate_limit

    event = {"type": "result", "is_error": True, "api_error_status": "529"}
    assert detect_rate_limit(json.dumps(event))
    event["api_error_status"] = 400
    assert not detect_rate_limit(json.dumps(event))


def test_claude_command_isolates_user_settings_by_default(monkeypatch):
    from swebench.issue_pipeline.offline_claude_pilot import claude_command

    monkeypatch.delenv("SWEBENCH_CLAUDE_ISOLATE", raising=False)
    command = claude_command()
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    monkeypatch.setenv("SWEBENCH_CLAUDE_ISOLATE", "0")
    command = claude_command()
    assert "--setting-sources" not in command
    assert "--strict-mcp-config" not in command
