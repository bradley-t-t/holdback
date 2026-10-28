"""Which of the person's messages decides a turn, read from transcripts as Claude Code
writes them, and the verdict that is kept for it. Nothing here reaches a real judge.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import time
import unittest
from unittest import mock

from helpers import (FakeJudge, called, event, human, peer, queued, reset_state, result, said,
                     transcript)
from holdback import judge as judges
from holdback import state, transcript as tr, turn


def decided_by(entries):
    """(words, before, approved) for the turn that ends the transcript."""
    read, whole = tr.read_window(transcript(entries), None)
    return tr.case(read, whole)


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

    def test_a_short_correction_carries_the_request_it_corrects(self):
        words, before, _ = decided_by([human("Create 5 text files in documents, random files."),
                                       said("Which folder did you want?"), human("Downloads I mean")])
        self.assertEqual(words, "Create 5 text files in documents, random files.\n\n"
                                "(Correcting that request) Downloads I mean")
        self.assertEqual(before, "Which folder did you want?")
        self.assertTrue(judges.scan(words, before).work)

    def test_a_critique_is_not_a_correction(self):
        for text in ("you missed the README", "That's wrong, the port is 8080 not 3000.",
                     "Why did you put it in Documents? I mean, really?"):
            with self.subTest(text=text):
                words, _, _ = decided_by([human("Fix the login bug."), said("Fixed."), human(text)])
                self.assertEqual(words, text)

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
        entries, whole = tr.read_window(path, 512 * 1024)
        self.assertFalse(whole)
        self.assertIs(tr.case(entries, whole), tr.MORE)
        reset_state()
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            self.assertTrue(turn.decided(path, "s-window").work)
        self.assertEqual(judge.calls[0][0], "Fix it.")


class Projects(unittest.TestCase):
    def wake(self, text, frm="human"):
        return {"type": "user", "message": {"content": '<wake reason="mention"><project id="p"><message '
                                                       'trigger="true" from="%s" id="m">%s</message>'
                                                       "</project></wake>" % (frm, text)}}

    def test_the_persons_words_in_a_wake(self):
        path = transcript([self.wake("Is it live &amp; tested?")])
        self.assertTrue(tr.project_session(path))
        entries, whole = tr.read_window(path)
        self.assertEqual(tr.project_case(entries, whole)[0], "Is it live & tested?")

    def test_a_thread_the_coordinator_started_has_none(self):
        path = transcript([self.wake("Do the migration.", frm="agent")])
        entries, whole = tr.read_window(path)
        self.assertIsNone(tr.project_case(entries, whole))


class Verdicts(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_one_judge_call_per_message(self):
        path = transcript([human("Why is it slow?")])
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            for _ in range(3):
                self.assertFalse(turn.decided(path, "s1").work)
        self.assertEqual(len(judge.calls), 1)

    def test_a_new_message_gets_its_own_verdict(self):
        entries = [human("Why is it slow?"), said("Because of X.")]
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            self.assertFalse(turn.decided(transcript(entries), "s2").work)
            self.assertTrue(turn.decided(transcript(entries + [human("Fix it.")]), "s2").work)
        self.assertEqual(len(judge.calls), 2)
        self.assertEqual(judge.calls[1], ("Fix it.", "Because of X."))

    def test_a_correction_after_a_request_lets_the_work_through(self):
        path = transcript([human("Create 5 text files in documents, random files."),
                           said("Creating them in ~/Documents."), human("Downloads I mean")])
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            self.assertTrue(turn.decided(path, "s-correct").work)
        self.assertIn("Create 5 text files", judge.calls[0][0])

    def test_a_slash_command_and_a_plan_need_no_judge(self):
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            self.assertTrue(turn.decided(transcript([human("/commit")]), "s3").work)
            self.assertTrue(turn.decided(transcript([
                human("Plan it."), called("ExitPlanMode", {}, tid="p"),
                result("p", "User has approved your plan.")]), "s3").work)
        self.assertEqual(judge.calls, [])

    def test_a_caller_can_pass_the_persons_words(self):
        path = transcript([human("Answer in two plain sentences. Is it on main?\n\n(Asked by voice ...)")])
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge), \
                mock.patch.dict(os.environ, {"TETHER_QUESTION": "Is it on main?"}):
            turn.decided(path, "s4")
        self.assertEqual(judge.calls[0][0], "Is it on main?")

    def test_a_subagent_goes_by_the_turn_that_launched_it(self):
        path = transcript([
            human("Write the universe file."), called("Agent", {"prompt": "write it"}, tid="a1"),
            result("a1", "Async agent launched successfully.\nagentId: a97f467ca01568c81"), said("Started."),
            human("Why is the sky blue?")])
        judge = FakeJudge(work_words=("write",))
        with mock.patch.object(judges, "judge", judge):
            self.assertFalse(turn.decided(path, "s5").work)
            self.assertTrue(turn.decided(path, "s5", "a97f467ca01568c81").work)
            self.assertFalse(turn.decided(path, "s5", "not-launched-yet").work)

    def test_a_verdict_another_process_is_working_out_is_waited_for(self):
        path = transcript([human("Why?")])
        judge = FakeJudge()
        with mock.patch.object(judges, "judge", judge):
            turn.decided(path, "s6")
        kept = state.load("s6")
        key = next(iter(kept["verdicts"]))
        kept["verdicts"] = {}
        kept["pending"] = {key: [time.time(), 1]}        # pid 1 is always alive
        state.save("s6", kept)
        with mock.patch.object(state, "WAIT", 0.5), mock.patch.object(judges, "judge", judge):
            v = turn.decided(path, "s6")
        self.assertEqual(len(judge.calls), 1)            # it waited, then fell back to the scan
        self.assertEqual(v.by, "scan")


if __name__ == "__main__":
    unittest.main()
