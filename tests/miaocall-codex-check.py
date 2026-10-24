#!/usr/bin/env python3
"""Offline contract tests for the MiaoCall official stdio adapter (no model)."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import miao_call


URI = "spotify:track:0123456789ABCDEFGHIJKL"
OTHER_URI = "spotify:track:abcdefghijklmnopqrstuv"
PAYLOAD = {"transcript": "打开 Spotify，播放示例歌曲", "tracks": [{"uri": URI, "title": "示例歌曲", "artist": "示例艺人", "aliases": ["歌曲"]}]}

FAKE_SERVER = r'''
import json, os, sys, time
mode = MODE
uri = URI
thread_id = "thread-fixture"
turn_id = "turn-fixture"
def send(value):
    print(json.dumps(value), flush=True)
def respond(message, result):
    send({"id":message["id"],"result":result})
def tool(name, arguments, call_id="tool-1"):
    send({"id":call_id,"method":"item/tool/call","params":{"tool":name,"namespace":None,"arguments":arguments,"threadId":thread_id,"turnId":turn_id,"callId":call_id}})
print("private-stderr-sentinel sk-DO-NOT-EXPOSE", file=sys.stderr, flush=True)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        assert message["params"]["capabilities"]["experimentalApi"] is True
        respond(message, {"userAgent":"fake-official-shape"})
    elif method == "account/read":
        respond(message, {"account":None if mode == "unauthenticated" else {"type":"chatgpt","email":"DO-NOT-EXPOSE@example.test"}})
    elif method == "thread/start":
        params = message["params"]
        assert params["ephemeral"] is True and params["sandbox"] == "read-only"
        assert params["approvalPolicy"] == "on-request"
        assert [x["name"] for x in params["dynamicTools"]] == ["playTrackUri","getPlayback"]
        for name in ("shell_tool","unified_exec","multi_agent","apps","plugins","computer_use"):
            assert params["config"]["features"][name] is False
        assert params["config"]["web_search"] == "disabled"
        assert not os.listdir(params["cwd"])
        respond(message, {"thread":{"id":thread_id,"ephemeral":True},"sandbox":{"type":"readOnly","networkAccess":False}})
    elif method == "turn/start":
        respond(message, {"turn":{"id":turn_id,"status":"inProgress"}})
        send({"method":"turn/started","params":{"threadId":thread_id,"turn":{"id":turn_id,"status":"inProgress"}}})
        if mode in ("hang","cancel"):
            continue
        if mode == "formal_only":
            send({"method":"item/agentMessage/delta","params":{"delta":"private reply sentinel"}})
            send({"method":"turn/completed","params":{"threadId":thread_id,"turn":{"id":turn_id,"status":"completed"}}})
        elif mode == "arbitrary_shell":
            send({"method":"item/started","params":{"threadId":thread_id,"turnId":turn_id,"item":{"type":"commandExecution","command":"DO-NOT-RUN"}}})
        elif mode == "approval":
            send({"id":"approval-1","method":"item/commandExecution/requestApproval","params":{"threadId":thread_id,"turnId":turn_id}})
        elif mode == "bad_namespace":
            send({"id":"tool-1","method":"item/tool/call","params":{"tool":"playTrackUri","arguments":{"uri":uri},"threadId":"different-thread","turnId":turn_id}})
        else:
            tool("playTrackUri", {"uri":OTHER_URI if mode == "wrong_uri" else uri})
    elif method == "turn/interrupt":
        respond(message,{})
        send({"method":"turn/completed","params":{"threadId":thread_id,"turn":{"id":turn_id,"status":"interrupted"}}})
    elif "id" in message and not method:
        if message["id"] == "approval-1":
            assert message["result"]["decision"] == "decline"
            continue
        assert "success" in message["result"]
        if mode == "readback" and message["id"] == "tool-1":
            tool("getPlayback",{},"tool-2")
        else:
            status = "failed" if mode == "failed_terminal" else "completed"
            send({"method":"turn/completed","params":{"threadId":thread_id,"turn":{"id":turn_id,"status":status}}})
'''


class HostInput:
    def __init__(self):
        self.messages = queue.Queue()

    def readline(self, limit=-1):
        return self.messages.get()

    def put(self, value):
        self.messages.put(json.dumps(value) + "\n")

    def close(self):
        self.messages.put("")


class MiaoCallCodexTests(unittest.TestCase):
    def execute(self, mode="success", host=None, timeout=None):
        events = []
        stream = HostInput()
        def emit(event):
            events.append(event)
            if mode == "cancel" and event.get("state") == "thinking":
                stream.put({"type":"cancel"})
            if event.get("type") == "tool":
                observation = {"playing":True,"verified":True,"uri":URI,"positionMs":1200,"title":"示例歌曲","artist":"示例艺人"}
                if mode in ("unverified", "readback") and event["arguments"]["action"] == "playTrackUri":
                    observation["verified"] = False
                if host:
                    observation = host(event, observation)
                stream.put({"type":"toolResult","id":event["id"],"result":observation})
        with tempfile.TemporaryDirectory(prefix="miaocall-offline-") as directory:
            executable = Path(directory) / "codex-fixture"
            fixture = FAKE_SERVER.replace("mode = MODE", "mode = " + repr(mode)).replace("uri = URI", "uri = " + repr(URI)).replace("OTHER_URI", repr(OTHER_URI))
            executable.write_text("#!" + sys.executable + "\n" + textwrap.dedent(fixture))
            executable.chmod(0o700)
            async def run():
                task = miao_call.CodexTask(PAYLOAD, emit, stream, cli=str(executable))
                result = await task.execute()
                self.assertTrue(task.closed)
                if task.proc:
                    self.assertIsNotNone(task.proc.returncode)
                return result
            try:
                with patch.object(miao_call,"MAX_TASK_SECONDS",timeout or 5):
                    result = asyncio.run(run())
            finally:
                stream.close()
        return result, events

    def test_confirmed_playback_and_formal_completion(self):
        result, events = self.execute()
        self.assertTrue(result["ok"])
        self.assertEqual(result["playback"]["uri"], URI)
        self.assertEqual(events[-1]["state"],"completed")
        self.assertTrue(any(x.get("type")=="tool" for x in events))

    def test_opening_app_without_verified_audio_is_not_success(self):
        result, events = self.execute("unverified")
        self.assertEqual(result["code"],"playback_not_verified")
        self.assertFalse(any(x.get("state")=="completed" for x in events))

    def test_formal_model_reply_alone_is_not_success(self):
        result, _ = self.execute("formal_only")
        self.assertEqual(result["code"],"playback_not_verified")

    def test_model_can_get_host_readback_after_play(self):
        result, events = self.execute("readback")
        self.assertTrue(result["ok"])
        self.assertEqual([x["arguments"]["action"] for x in events if x.get("type")=="tool"],["playTrackUri","getPlayback"])

    def test_failed_terminal_never_success_even_if_spotify_playing(self):
        result, _ = self.execute("failed_terminal")
        self.assertEqual(result["code"],"codex_task_failed")

    def test_song_not_in_catalog_is_rejected_before_host_tool(self):
        result, events = self.execute("wrong_uri")
        self.assertEqual(result["code"],"scope_not_supported")
        self.assertFalse(any(x.get("type")=="tool" for x in events))

    def test_mismatched_thread_tool_is_rejected(self):
        result, events = self.execute("bad_namespace")
        self.assertEqual(result["code"],"scope_not_supported")
        self.assertFalse(any(x.get("type")=="tool" for x in events))

    def test_shell_approval_is_declined(self):
        result, _ = self.execute("approval")
        self.assertEqual(result["code"],"scope_not_supported")

    def test_unexpected_shell_item_stops_task(self):
        result, _ = self.execute("arbitrary_shell")
        self.assertEqual(result["code"],"scope_not_supported")

    def test_cancellation_interrupts_and_closes_process(self):
        result, events = self.execute("cancel")
        self.assertEqual(result["status"],"cancelled")
        self.assertEqual(events[-1]["state"],"cancelled")

    def test_timeout_closes_process(self):
        result, _ = self.execute("hang",timeout=0.3)
        self.assertEqual(result["code"],"timeout")

    def test_signin_failure_is_local_and_actionable(self):
        result, _ = self.execute("unauthenticated")
        self.assertEqual(result["code"],"codex_auth_required")

    def test_provider_stderr_account_and_transcript_never_in_events(self):
        result, events = self.execute()
        serialized = json.dumps([result,events],ensure_ascii=False)
        for secret in ("sk-DO-NOT-EXPOSE","private-stderr-sentinel","DO-NOT-EXPOSE@example.test",PAYLOAD["transcript"],"private reply sentinel"):
            self.assertNotIn(secret,serialized)

    def test_untrusted_playback_output_is_bounded_and_allowlisted(self):
        value = miao_call.safe_playback({"playing":True,"verified":True,"uri":OTHER_URI,"positionMs":-1,"extra":"secret","title":"a"*2000},{URI})
        self.assertFalse(value["verified"])
        self.assertNotIn("uri",value)
        self.assertNotIn("positionMs",value)
        self.assertNotIn("extra",value)
        self.assertEqual(len(value["title"]),180)

    def test_payload_rejects_uris_shell_paths_and_empty_instructions(self):
        for changes in ({"transcript":""},{"tracks":[]},{"model":"$(shell)"},{"tracks":[{"uri":"file:///Users/private","title":"x","artist":"y"}]}):
            with self.subTest(changes=changes),self.assertRaises(miao_call.MiaoCallError):
                miao_call.validate_payload({**PAYLOAD,**changes})


if __name__ == "__main__":
    unittest.main(verbosity=2)
