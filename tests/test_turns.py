"""Which of the person's messages decides a turn, read from transcripts as Claude Code writes
them. Nothing here reaches the judge.

Run:  python3 -m unittest discover -s tests -v
"""
import json, os, unittest
from unittest import mock

from helpers import (holdback, transcript, human, queued, event, peer, said, called, result, FakeJudge,
                     reset_state)


def decided_by(entries, **kw):
    """(words, before, approved) for the turn that ends the transcript."""
    entries_, whole = holdback.read_window(transcript(entries), None)
    return holdback.case(entries_, whole)


class Turns(unittest.TestCase):
    def test_a_persons_message_decides_its_turn(self):
        words, before, approved = decided_by([human("Why is the build failing?"), said("The lockfile is stale."),
                                              human("Fix it.")])
        self.assertEqual(words, "Fix it.")
        self.assertEqual(before, "The lockfile is stale.")
        self.assertFalse(approved)

    def test_the_app_reminder_is_not_their_words(self):
        words, _, _ = decided_by([human("<system-reminder>\nYou are in a worktree.\n</system-reminder>\nWhy?")])
        self.assertEqual(words, "Why?")

    def test_a_message_sent_while_it_runs_joins_the_turn(self):
        words, _, _ = decided_by([human("Why is it slow?"), said("Looking."), queued("Go ahead and fix it.")])
        self.assertEqual(words, "Why is it slow?\n\nGo ahead and fix it.")

    def test_a_status_check_goes_by_the_request(self):
        words, _, _ = decided_by([human("Fix the login bug."), said("On it."), human("Status?")])
        self.assertEqual(words, "Fix the login bug.")

    def test_an_automated_turn_goes_by_the_open_request(self):
        for start in (event("<task-notification>done</task-notification>"),
                      event("<ci-monitor-event>failed</ci-monitor-event>", kind="ci"),
                      peer("Heads-up: your worktree moved.")):
            with self.subTest(start=str(start)[:60]):
                words, _, _ = decided_by([human("Why does the test fail?"), said("Because X."), start])
                self.assertEqual(words, "Why does the test fail?")

    def test_the_person_speaking_in_an_automated_turn_decides_it(self):
        words, _, _ = decided_by([human("Why?"), said("Because."), event("<task-notification>x</task-notification>"),
                                  queued("Ship it.")])
        self.assertEqual(words, "Ship it.")

    def test_words_relayed_by_voice_are_the_persons(self):
        body = ("Is the checkout on main?\n\n(Asked by voice through the Sunday speaker, which is waiting on your "
                "answer. Answer in two or three plain sentences, then post that answer back by running: ssh pi ...)")
        words, _, _ = decided_by([human("Fix the build."), said("Fixed."), peer(body, name="Sunday")])
        self.assertEqual(words, "Is the checkout on main?")

    def test_a_slash_command_is_the_persons(self):
        words, _, _ = decided_by([human("<command-message>ship is running</command-message>\n<command-name>/ship"
                                        "</command-name>\n<command-args>all</command-args>")])
        self.assertEqual(words, "/ship all")

    def test_an_answer_to_the_assistants_question_counts(self):
        words, _, _ = decided_by([human("Which cache should we use?"), called("AskUserQuestion", {}, tid="t1"),
                                  result("t1", 'User has answered your questions: "Which?"="Redis, set it up". '
                                               "You can now continue with the user's answers in mind.")])
        self.assertIn('"Which?"="Redis, set it up"', words)

    def test_an_approved_plan_counts(self):
        _, _, approved = decided_by([human("Plan the migration."), called("ExitPlanMode", {"plan": "x"}, tid="t2"),
                                     result("t2", "User has approved your plan. You can now start coding.")])
        self.assertTrue(approved)

    def test_no_person_no_turn(self):
        self.assertIsNone(decided_by([event("<task-notification>x</task-notification>")]))

    def test_a_short_window_reaches_back(self):
        filler = [said("x" * 2000) for _ in range(400)]
        path = transcript([human("Fix it."), *filler, event("<task-notification>x</task-notification>")])
        entries, whole = holdback.read_window(path, 512 * 1024)
        self.assertFalse(whole)
        self.assertIs(holdback.case(entries, whole), holdback.MORE)
        reset_state()
        judge = FakeJudge()
        with mock.patch.object(holdback, "judge", judge):
            self.assertTrue(holdback.decided(path, "s-window")["work"])
        self.assertEqual(judge.calls[0][0], "Fix it.")


class Projects(unittest.TestCase):
    def wake(self, text, frm="human"):
        return {"type": "user", "message": {"content": f'<wake reason="mention"><project id="p"><message '
                                                       f'trigger="true" from="{frm}" id="m">{text}</message>'
                                                       f'</project></wake>'}}

    def test_the_persons_words_in_a_wake(self):
        path = transcript([self.wake("Is it live &amp; tested?")])
        self.assertTrue(holdback.project_session(path))
        entries, whole = holdback.read_window(path)
        self.assertEqual(holdback.project_case(entries, whole)[0], "Is it live & tested?")

    def test_a_thread_the_coordinator_started_has_none(self):
        path = transcript([self.wake("Do the migration.", frm="agent")])
        entries, whole = holdback.read_window(path)
        self.assertIsNone(holdback.project_case(entries, whole))


class Verdicts(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_one_judge_call_per_message(self):
        path = transcript([human("Why is it slow?")])
        judge = FakeJudge()
        with mock.patch.object(holdback, "judge", judge):
            for _ in range(3):
                self.assertFalse(holdback.decided(path, "s1")["work"])
        self.assertEqual(len(judge.calls), 1)

    def test_a_new_message_gets_its_own_verdict(self):
        entries = [human("Why is it slow?"), said("Because of X.")]
        judge = FakeJudge()
        with mock.patch.object(holdback, "judge", judge):
            self.assertFalse(holdback.decided(transcript(entries), "s2")["work"])
            self.assertTrue(holdback.decided(transcript(entries + [human("Fix it.")]), "s2")["work"])
        self.assertEqual(len(judge.calls), 2)
        self.assertEqual(judge.calls[1], ("Fix it.", "Because of X."))

    def test_a_slash_command_and_a_plan_need_no_judge(self):
        judge = FakeJudge()
        with mock.patch.object(holdback, "judge", judge):
            self.assertTrue(holdback.decided(transcript([human("/commit")]), "s3")["work"])
            self.assertTrue(holdback.decided(transcript([
                human("Plan it."), called("ExitPlanMode", {}, tid="p"), result("p", "User has approved your plan.")]),
                "s3")["work"])
        self.assertEqual(judge.calls, [])

    def test_a_caller_can_pass_the_persons_words(self):
        path = transcript([human("Answer in two plain sentences. Is it on main?\n\n(Asked by voice ...)")])
        judge = FakeJudge()
        with mock.patch.object(holdback, "judge", judge), mock.patch.dict(os.environ, {"TETHER_QUESTION": "Is it on main?"}):
            holdback.decided(path, "s4")
        self.assertEqual(judge.calls[0][0], "Is it on main?")

    def test_a_subagent_goes_by_the_turn_that_launched_it(self):
        path = transcript([
            human("Write the universe file."), called("Agent", {"prompt": "write it"}, tid="a1"),
            result("a1", "Async agent launched successfully.\nagentId: a97f467ca01568c81"), said("Started."),
            human("Why is the sky blue?")])
        judge = FakeJudge(work_words=("write",))
        with mock.patch.object(holdback, "judge", judge):
            self.assertFalse(holdback.decided(path, "s5")["work"])
            self.assertTrue(holdback.decided(path, "s5", "a97f467ca01568c81")["work"])
            self.assertFalse(holdback.decided(path, "s5", "not-launched-yet")["work"])

    def test_the_word_scan_decides_when_the_judge_cannot(self):
        with mock.patch.object(holdback, "claude_bin", return_value="/nonexistent/claude"):
            v = holdback.judge("Why is the build failing?")
            self.assertFalse(v["work"])
            self.assertIn("error", v)
            self.assertTrue(holdback.judge("Fix it, test it, then release it.")["work"])

    def test_a_verdict_another_process_is_working_out_is_waited_for(self):
        path = transcript([human("Why?")])
        key_judge = FakeJudge()
        with mock.patch.object(holdback, "judge", key_judge):
            v = holdback.decided(path, "s6")
        state = holdback.load("s6")
        key = next(iter(state["verdicts"]))
        state["verdicts"] = {}
        state["pending"] = {key: [__import__("time").time(), 1]}       # pid 1 is always alive
        holdback.save("s6", state)
        with mock.patch.object(holdback, "WAIT", 0.5), mock.patch.object(holdback, "judge", key_judge):
            v = holdback.decided(path, "s6")
        self.assertEqual(len(key_judge.calls), 1)                      # it waited, then fell back to the scan
        self.assertEqual(v["by"], "scan")


class Scan(unittest.TestCase):
    def test_messages(self):
        for message, before, want in [
            ("Fix it, test it, then release it.", "", True), ("Can you fix the login bug?", "", True),
            ("That's wrong, change it to 8080.", "", True), ("yes", "Want me to make that change?", True),
            ("/ship", "", True), ("Why is the build failing?", "", False),
            ("Explain again concisely.", "", False), ("Propose a plan to fix the issues.", "", False),
            ("That's wrong, the port is 8080 not 3000.", "", False), ("ok thanks", "The build is fixed.", False),
            ("Fix the bug. Actually wait, don't change anything yet.", "", False),
            ("It isn't supposed to say it left work undone.", "", False),
        ]:
            with self.subTest(message=message):
                self.assertEqual(holdback.scan(message, before)["work"], want)


if __name__ == "__main__":
    unittest.main()
