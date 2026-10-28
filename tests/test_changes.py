"""What a tool call would change: the calls a question turn must still be able to make
(reading, searching, Tether's draft check, the scratchpad) and the ones Holdback holds.
Nothing here reaches a judge.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import unittest

import helpers  # noqa: F401  (puts src on the path and points the state at a temp folder)
from holdback.changes import changes

SP = "/private/tmp/claude-501/-Users-someone/0000/scratchpad"
HOME = os.path.expanduser("~")
CWD = "/Users/someone/Development/project"


@helpers.posix_only
class Tools(unittest.TestCase):
    def check(self, name, inp=None, want=None):
        got = changes(name, inp or {}, CWD)
        if want is None:
            self.assertIsNone(got, name)
        else:
            self.assertTrue(got, name)

    def test_reading_and_answering_tools(self):
        for name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch", "TodoWrite", "Agent", "Skill",
                     "AskUserQuestion", "SendUserFile", "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up",
                     "mcp__ccd_view__show_pane", "mcp__ccd_session_mgmt__list_sessions",
                     "mcp__Claude_Browser__navigate", "mcp__Claude_Browser__get_page_text",
                     "mcp__claude-in-chrome__read_page", "mcp__0917__list_tables", "mcp__0917__search_docs",
                     "mcp__fcb3__outlook_email_search", "mcp__fcb3__teams_list_channels", "mcp__5882__get_screenshot",
                     "mcp__5882__create_session", "mcp__f786__handoff_wait", "mcp__terminal__read_terminal",
                     "mcp__computer-use__app_screenshot", "mcp__scheduled-tasks__list_scheduled_tasks",
                     "mcp__ca47__get_runtime_logs", "mcp__ca47__aggregate_pageviews", "mcp__visualize__show_widget"):
            with self.subTest(tool=name):
                self.check(name)

    def test_tools_that_change_things(self):
        for name in ("mcp__0917__apply_migration", "mcp__0917__deploy_edge_function", "mcp__fcb3__outlook_send_mail",
                     "mcp__fcb3__outlook_create_draft", "mcp__fcb3__teams_send_chat_message", "mcp__5882__use_figma",
                     "mcp__f786__handoff", "mcp__ccd_session__hand_off_to_session", "mcp__ccd_settings__set_setting",
                     "mcp__ccd_pr__set_auto_merge", "mcp__ccd_host__sync_with_base_branch",
                     "mcp__computer-use__app_click", "mcp__computer-use__app_type", "mcp__claude-in-chrome__form_input",
                     "mcp__scheduled-tasks__create_scheduled_task", "mcp__ca47__create_deployment",
                     "mcp__Read_and_Write_Apple_Notes__add_note", "mcp__unreal__call_tool", "CronCreate",
                     "ScheduleWakeup", "RemoteTrigger", "EnterWorktree", "SendMessage",
                     "mcp__ccd_session_mgmt__send_message", "mcp__ccd_session_mgmt__archive_session"):
            with self.subTest(tool=name):
                self.check(name, want=True)

    def test_files(self):
        self.check("Write", {"file_path": "%s/draft.md" % SP})
        self.check("Write", {"file_path": "%s/.claude/projects/-Users-x/memory/feedback.md" % HOME})
        self.check("Write", {"file_path": "%s/.claude/plans/plan.md" % HOME})
        self.check("Edit", {"file_path": "%s/src/app.py" % CWD}, want=True)
        self.check("Write", {"file_path": "%s/.claude/CLAUDE.md" % HOME}, want=True)
        self.check("NotebookEdit", {"notebook_path": "%s/a.ipynb" % CWD}, want=True)

    def test_inputs_decide(self):
        self.check("Bash", {"command": "git status"})
        self.check("Bash", {"command": "git push"}, want=True)
        self.check("mcp__terminal__run_in_terminal", {"command": "npm install"}, want=True)
        self.check("mcp__0917__execute_sql", {"query": "select * from users where id = 1"})
        self.check("mcp__0917__execute_sql", {"query": "select 1; delete from users"}, want=True)
        self.check("mcp__0917__execute_sql", {"query": "update users set name = 'x'"}, want=True)
        self.check("Artifact", {"action": "read", "url": "x"})
        self.check("Artifact", {"file_path": "/tmp/x.html"}, want=True)
        self.check("ArtifactData", {"action": "query"})
        self.check("ArtifactData", {"action": "set"}, want=True)
        self.check("mcp__ccd_session__start_session", {"initiation": "own_initiative"})
        self.check("mcp__ccd_session__start_session", {"initiation": "user_asked"}, want=True)
        self.check("mcp__Claude_Browser__computer", {"action": "screenshot"})
        self.check("mcp__Claude_Browser__computer", {"action": "left_click"}, want=True)
        self.check("mcp__Claude_Browser__browser_batch", {"actions": [
            {"name": "navigate", "input": {"url": "x"}}, {"name": "computer", "input": {"action": "screenshot"}}]})
        self.check("mcp__Claude_Browser__browser_batch", {"actions": [
            {"name": "computer", "input": {"action": "type", "text": "x"}}]}, want=True)
        self.check("mcp__Claude_Code_iOS_Simulator__control", {"action": "screenshot"})
        self.check("mcp__Claude_Code_iOS_Simulator__control", {"action": "tap"}, want=True)

    def test_a_project_session_answers_with_its_reply_tools(self):
        self.check("mcp__hearthbot__reply", {"text": "x"})
        self.check("mcp__hearthbot__post_message", {"text": "x"})
        self.check("mcp__hearthbot__start_thread_session", {"brief": "x"}, want=True)
        self.check("mcp__other__reply", {"text": "x"}, want=True)


if __name__ == "__main__":
    unittest.main()
