"""
Tests for omnix.collab — Real-time Collaboration module.

Covers: session lifecycle, sync conflict resolution, presence tracking,
collaborative history with per-user undo, and the WS handler coordinator.
"""

import sys
import os
import time
import unittest

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from omnix.collab.session import CollabSession, SessionStore, Peer, _generate_share_code
from omnix.collab.sync import SyncEngine, Change, ChangeType, ConflictInfo
from omnix.collab.presence import PresenceTracker, CursorPosition, PeerPresence
from omnix.collab.history import CollabHistory, HistoryEntry
from omnix.collab.ws_handler import CollabWSHandler


# ═══════════════════════════════════════════════════════════
#  Session Tests
# ═══════════════════════════════════════════════════════════

class TestPeer(unittest.TestCase):
    def test_peer_to_dict(self):
        p = Peer(peer_id="p1", name="Alice", color="#FF6B6B")
        d = p.to_dict()
        self.assertEqual(d["peer_id"], "p1")
        self.assertEqual(d["name"], "Alice")
        self.assertEqual(d["color"], "#FF6B6B")
        self.assertTrue(d["connected"])
        self.assertEqual(d["active_view"], "3d")

    def test_peer_defaults(self):
        p = Peer(peer_id="p1", name="Bob", color="#4ECDC4")
        self.assertIsNone(p.cursor)
        self.assertIsNone(p.selected_part)
        self.assertIsNone(p.selected_node)
        self.assertFalse(p.typing)


class TestCollabSession(unittest.TestCase):
    def test_create_session(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        self.assertEqual(s.session_id, "s1")
        self.assertEqual(s.share_code, "ABC123")
        self.assertEqual(s.owner_id, "u1")
        self.assertEqual(len(s.peers), 0)

    def test_join_assigns_unique_colors(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        p1 = s.join("u1", "Alice")
        p2 = s.join("u2", "Bob")
        p3 = s.join("u3", "Charlie")
        self.assertNotEqual(p1.color, p2.color)
        self.assertNotEqual(p2.color, p3.color)
        self.assertNotEqual(p1.color, p3.color)

    def test_join_reconnect(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        p1 = s.join("u1", "Alice")
        original_color = p1.color
        s.leave("u1")
        self.assertFalse(p1.connected)
        p1_back = s.join("u1", "Alice")
        self.assertTrue(p1_back.connected)
        self.assertEqual(p1_back.color, original_color)  # Keep original color

    def test_leave(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        s.join("u1", "Alice")
        peer = s.leave("u1")
        self.assertIsNotNone(peer)
        self.assertFalse(peer.connected)

    def test_leave_nonexistent(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        peer = s.leave("nobody")
        self.assertIsNone(peer)

    def test_remove(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        s.join("u1", "Alice")
        removed = s.remove("u1")
        self.assertIsNotNone(removed)
        self.assertEqual(len(s.peers), 0)

    def test_active_peers(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        s.join("u1", "Alice")
        s.join("u2", "Bob")
        s.leave("u1")
        active = s.active_peers()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].peer_id, "u2")

    def test_chat(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        msg = s.add_chat("u1", "Hello!")
        self.assertEqual(msg["peer_id"], "u1")
        self.assertEqual(msg["text"], "Hello!")
        self.assertEqual(len(s.chat_messages), 1)

    def test_to_dict(self):
        s = CollabSession(session_id="s1", share_code="ABC123", owner_id="u1")
        s.join("u1", "Alice")
        d = s.to_dict(include_chat=True)
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(d["share_code"], "ABC123")
        self.assertEqual(len(d["peers"]), 1)
        self.assertEqual(d["active_count"], 1)
        self.assertIn("chat", d)


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore()

    def test_create_and_get(self):
        session = self.store.create("u1", "Alice", "dev-1")
        self.assertIsNotNone(session.session_id)
        self.assertEqual(len(session.share_code), 6)
        self.assertEqual(session.owner_id, "u1")
        self.assertEqual(session.workspace_device_id, "dev-1")
        # Owner auto-joined
        self.assertEqual(len(session.peers), 1)
        # Retrieve by ID
        got = self.store.get(session.session_id)
        self.assertEqual(got.session_id, session.session_id)

    def test_get_by_code(self):
        session = self.store.create("u1", "Alice")
        found = self.store.get_by_code(session.share_code)
        self.assertIsNotNone(found)
        self.assertEqual(found.session_id, session.session_id)
        # Case insensitive
        found_lower = self.store.get_by_code(session.share_code.lower())
        self.assertIsNotNone(found_lower)

    def test_get_by_code_not_found(self):
        self.assertIsNone(self.store.get_by_code("ZZZZZ9"))

    def test_remove(self):
        session = self.store.create("u1", "Alice")
        self.assertTrue(self.store.remove(session.session_id))
        self.assertIsNone(self.store.get(session.session_id))
        self.assertIsNone(self.store.get_by_code(session.share_code))

    def test_list_all(self):
        self.store.create("u1", "Alice")
        self.store.create("u2", "Bob")
        lst = self.store.list_all()
        self.assertEqual(len(lst), 2)

    def test_find_by_peer(self):
        session = self.store.create("u1", "Alice")
        session.join("u2", "Bob")
        found = self.store.find_by_peer("u2")
        self.assertIsNotNone(found)
        self.assertEqual(found.session_id, session.session_id)
        self.assertIsNone(self.store.find_by_peer("nobody"))


class TestShareCodeGeneration(unittest.TestCase):
    def test_code_length(self):
        code = _generate_share_code(6)
        self.assertEqual(len(code), 6)

    def test_code_characters(self):
        # Should not contain 0, O, 1, I
        for _ in range(50):
            code = _generate_share_code()
            for c in code:
                self.assertNotIn(c, '0O1I')


# ═══════════════════════════════════════════════════════════
#  Sync / Conflict Resolution Tests
# ═══════════════════════════════════════════════════════════

class TestSyncEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SyncEngine()
        self.engine.init_session("s1")
        self.engine.register_peer("s1", "p1")
        self.engine.register_peer("s1", "p2")

    def test_apply_change(self):
        change = Change(
            change_id="c1", session_id="s1", peer_id="p1",
            change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
            data={"size": 10},
        )
        conflict = self.engine.apply_change(change)
        self.assertIsNone(conflict)
        self.assertEqual(change.seq, 1)

    def test_sequence_numbers(self):
        for i in range(5):
            c = Change(change_id=f"c{i}", session_id="s1", peer_id="p1",
                       change_type=ChangeType.PART_UPDATE, target_id=f"part_{i}",
                       data={})
            self.engine.apply_change(c)
            self.assertEqual(c.seq, i + 1)

    def test_conflict_detection(self):
        """Two peers editing the same target within 3 seconds should trigger conflict."""
        now = time.time()
        c1 = Change(change_id="c1", session_id="s1", peer_id="p1",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={"size": 10}, timestamp=now)
        c2 = Change(change_id="c2", session_id="s1", peer_id="p2",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={"size": 15}, timestamp=now + 1)

        conflict1 = self.engine.apply_change(c1, {"p1": "Alice", "p2": "Bob"})
        self.assertIsNone(conflict1)

        conflict2 = self.engine.apply_change(c2, {"p1": "Alice", "p2": "Bob"})
        self.assertIsNotNone(conflict2)
        self.assertEqual(conflict2.conflicting_peer_id, "p1")
        self.assertEqual(conflict2.conflicting_peer_name, "Alice")
        self.assertEqual(conflict2.target_id, "rotor_1")

    def test_no_conflict_same_peer(self):
        """Same peer editing the same target shouldn't be a conflict."""
        now = time.time()
        c1 = Change(change_id="c1", session_id="s1", peer_id="p1",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={"size": 10}, timestamp=now)
        c2 = Change(change_id="c2", session_id="s1", peer_id="p1",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={"size": 15}, timestamp=now + 0.5)

        self.engine.apply_change(c1)
        conflict = self.engine.apply_change(c2)
        self.assertIsNone(conflict)

    def test_no_conflict_different_targets(self):
        """Editing different targets shouldn't conflict."""
        now = time.time()
        c1 = Change(change_id="c1", session_id="s1", peer_id="p1",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={}, timestamp=now)
        c2 = Change(change_id="c2", session_id="s1", peer_id="p2",
                     change_type=ChangeType.PART_UPDATE, target_id="motor_1",
                     data={}, timestamp=now + 0.5)

        self.engine.apply_change(c1)
        conflict = self.engine.apply_change(c2)
        self.assertIsNone(conflict)

    def test_no_conflict_after_timeout(self):
        """Edits to same target > 3s apart shouldn't conflict."""
        now = time.time()
        c1 = Change(change_id="c1", session_id="s1", peer_id="p1",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={}, timestamp=now)
        c2 = Change(change_id="c2", session_id="s1", peer_id="p2",
                     change_type=ChangeType.PART_UPDATE, target_id="rotor_1",
                     data={}, timestamp=now + 5)

        self.engine.apply_change(c1)
        conflict = self.engine.apply_change(c2)
        self.assertIsNone(conflict)

    def test_broadcast_to_other_peers(self):
        """Change by p1 should appear in p2's pending queue."""
        c = Change(change_id="c1", session_id="s1", peer_id="p1",
                   change_type=ChangeType.PART_ADD, target_id="new_part",
                   data={"name": "Wing"})
        self.engine.apply_change(c)

        p2_changes = self.engine.poll_changes("s1", "p2")
        self.assertEqual(len(p2_changes), 1)
        self.assertEqual(p2_changes[0]["target_id"], "new_part")

        # p1 should NOT see their own change
        p1_changes = self.engine.poll_changes("s1", "p1")
        self.assertEqual(len(p1_changes), 0)

    def test_poll_drains_queue(self):
        c = Change(change_id="c1", session_id="s1", peer_id="p1",
                   change_type=ChangeType.PART_ADD, target_id="x",
                   data={})
        self.engine.apply_change(c)
        self.engine.poll_changes("s1", "p2")  # Drain
        p2_again = self.engine.poll_changes("s1", "p2")
        self.assertEqual(len(p2_again), 0)

    def test_get_log(self):
        for i in range(3):
            c = Change(change_id=f"c{i}", session_id="s1", peer_id="p1",
                       change_type=ChangeType.NODE_ADD, target_id=f"n{i}",
                       data={})
            self.engine.apply_change(c)
        log = self.engine.get_log("s1", since_seq=1)
        self.assertEqual(len(log), 2)  # seq 2 and 3

    def test_cleanup(self):
        self.engine.cleanup_session("s1")
        self.assertEqual(self.engine.get_log("s1"), [])

    def test_change_from_dict(self):
        d = {
            "change_id": "c1",
            "session_id": "s1",
            "peer_id": "p1",
            "change_type": "part_update",
            "target_id": "rotor_1",
            "data": {"size": 10},
        }
        c = Change.from_dict(d)
        self.assertEqual(c.change_type, ChangeType.PART_UPDATE)
        self.assertEqual(c.target_id, "rotor_1")


# ═══════════════════════════════════════════════════════════
#  Presence Tests
# ═══════════════════════════════════════════════════════════

class TestPresenceTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = PresenceTracker()
        self.tracker.init_session("s1")

    def test_join_and_leave(self):
        pp = self.tracker.join("s1", "p1")
        self.assertEqual(pp.peer_id, "p1")
        self.assertEqual(pp.active_view, "3d")

        presence = self.tracker.get_session_presence("s1")
        self.assertEqual(len(presence), 1)

        self.tracker.leave("s1", "p1")
        presence = self.tracker.get_session_presence("s1")
        self.assertEqual(len(presence), 0)

    def test_update_cursor(self):
        self.tracker.join("s1", "p1")
        pp = self.tracker.update_cursor("s1", "p1", {
            "canvas_x": 100, "canvas_y": 200,
            "world_x": 1.5, "world_y": 2.5, "world_z": 0,
        })
        self.assertIsNotNone(pp)
        self.assertIsNotNone(pp.cursor)
        self.assertEqual(pp.cursor.canvas_x, 100)
        self.assertEqual(pp.cursor.canvas_y, 200)
        self.assertEqual(pp.cursor.world_x, 1.5)

    def test_update_view(self):
        self.tracker.join("s1", "p1")
        pp = self.tracker.update_view("s1", "p1", "mission")
        self.assertEqual(pp.active_view, "mission")

    def test_update_selection(self):
        self.tracker.join("s1", "p1")
        pp = self.tracker.update_selection("s1", "p1", part_id="rotor_1")
        self.assertEqual(pp.selected_part, "rotor_1")
        self.assertIsNone(pp.selected_node)

        pp = self.tracker.update_selection("s1", "p1", node_id="seq_1")
        self.assertIsNone(pp.selected_part)
        self.assertEqual(pp.selected_node, "seq_1")

    def test_update_typing(self):
        self.tracker.join("s1", "p1")
        pp = self.tracker.update_typing("s1", "p1", True)
        self.assertTrue(pp.typing)
        pp = self.tracker.update_typing("s1", "p1", False)
        self.assertFalse(pp.typing)

    def test_update_nonexistent_peer(self):
        self.assertIsNone(self.tracker.update_cursor("s1", "nobody", {}))
        self.assertIsNone(self.tracker.update_view("s1", "nobody", "3d"))

    def test_cleanup_stale(self):
        self.tracker.join("s1", "p1")
        self.tracker.join("s1", "p2")
        # Make p1 stale
        pp1 = self.tracker._presence["s1"]["p1"]
        pp1.last_activity = time.time() - 120  # 2 minutes ago

        stale = self.tracker.cleanup_stale("s1", timeout_s=60)
        self.assertEqual(stale, ["p1"])
        presence = self.tracker.get_session_presence("s1")
        self.assertEqual(len(presence), 1)
        self.assertEqual(presence[0]["peer_id"], "p2")

    def test_cursor_position_roundtrip(self):
        cp = CursorPosition(world_x=1, world_y=2, world_z=3,
                            canvas_x=100, canvas_y=200, view="mission")
        d = cp.to_dict()
        cp2 = CursorPosition.from_dict(d)
        self.assertEqual(cp2.world_x, 1)
        self.assertEqual(cp2.canvas_x, 100)
        self.assertEqual(cp2.view, "mission")


# ═══════════════════════════════════════════════════════════
#  History Tests
# ═══════════════════════════════════════════════════════════

class TestCollabHistory(unittest.TestCase):
    def setUp(self):
        self.history = CollabHistory(max_entries=50)
        self.history.init_session("s1")

    def test_record_entry(self):
        entry = self.history.record(
            session_id="s1", peer_id="p1", peer_name="Alice",
            peer_color="#FF6B6B", action="updated rotor_1 size",
            change_type="part_update", target_id="rotor_1",
            before_data={"size": 5}, after_data={"size": 10},
        )
        self.assertIsNotNone(entry.entry_id)
        self.assertEqual(entry.action, "updated rotor_1 size")
        self.assertFalse(entry.undone)

    def test_get_timeline(self):
        for i in range(5):
            self.history.record("s1", f"p{i%2+1}", f"User{i%2+1}", "#aaa",
                                f"action {i}", "part_update", f"part_{i}",
                                {}, {"val": i})
        timeline = self.history.get_timeline("s1")
        self.assertEqual(len(timeline), 5)

    def test_get_timeline_filtered(self):
        self.history.record("s1", "p1", "Alice", "#aaa", "a1", "part_update", "x", {}, {})
        self.history.record("s1", "p2", "Bob", "#bbb", "a2", "part_update", "y", {}, {})
        self.history.record("s1", "p1", "Alice", "#aaa", "a3", "part_update", "z", {}, {})

        p1_timeline = self.history.get_timeline("s1", peer_id="p1")
        self.assertEqual(len(p1_timeline), 2)

    def test_undo(self):
        self.history.record("s1", "p1", "Alice", "#aaa", "set size=10",
                            "part_update", "rotor_1",
                            {"size": 5}, {"size": 10})
        self.history.record("s1", "p1", "Alice", "#aaa", "set size=15",
                            "part_update", "rotor_1",
                            {"size": 10}, {"size": 15})

        # Undo last change by p1
        entry = self.history.undo("s1", "p1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "set size=15")
        self.assertTrue(entry.undone)
        self.assertEqual(entry.before_data, {"size": 10})  # Data to revert to

    def test_undo_only_own_changes(self):
        """p1 can only undo p1's changes, not p2's."""
        self.history.record("s1", "p1", "Alice", "#aaa", "a1",
                            "part_update", "x", {}, {})
        self.history.record("s1", "p2", "Bob", "#bbb", "a2",
                            "part_update", "y", {}, {})

        # p2 undoes — should get a2
        entry = self.history.undo("s1", "p2")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "a2")

        # p1 undoes — should get a1
        entry = self.history.undo("s1", "p1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "a1")

    def test_undo_empty_stack(self):
        entry = self.history.undo("s1", "p1")
        self.assertIsNone(entry)

    def test_undo_skips_already_undone(self):
        self.history.record("s1", "p1", "Alice", "#aaa", "a1",
                            "part_update", "x", {}, {})
        self.history.record("s1", "p1", "Alice", "#aaa", "a2",
                            "part_update", "y", {}, {})

        # Undo twice
        e1 = self.history.undo("s1", "p1")
        self.assertEqual(e1.action, "a2")
        e2 = self.history.undo("s1", "p1")
        self.assertEqual(e2.action, "a1")
        e3 = self.history.undo("s1", "p1")
        self.assertIsNone(e3)

    def test_max_entries(self):
        history = CollabHistory(max_entries=5)
        history.init_session("s1")
        for i in range(10):
            history.record("s1", "p1", "Alice", "#aaa", f"action_{i}",
                           "part_update", f"t{i}", {}, {})
        timeline = history.get_timeline("s1", limit=100)
        self.assertEqual(len(timeline), 5)

    def test_cleanup(self):
        self.history.record("s1", "p1", "Alice", "#aaa", "a1",
                            "part_update", "x", {}, {})
        self.history.cleanup_session("s1")
        self.assertEqual(self.history.get_timeline("s1"), [])


# ═══════════════════════════════════════════════════════════
#  WS Handler (Coordinator) Tests
# ═══════════════════════════════════════════════════════════

class TestCollabWSHandler(unittest.TestCase):
    def setUp(self):
        self.handler = CollabWSHandler()

    def test_create_session(self):
        result = self.handler.create_session("u1", "Alice", "dev-1")
        self.assertIn("session_id", result)
        self.assertIn("share_code", result)
        self.assertEqual(result["owner_id"], "u1")
        self.assertEqual(len(result["peers"]), 1)

    def test_join_session(self):
        created = self.handler.create_session("u1", "Alice")
        code = created["share_code"]

        joined = self.handler.join_session(code, "u2", "Bob")
        self.assertIsNotNone(joined)
        self.assertEqual(joined["peer"]["name"], "Bob")
        self.assertEqual(len(joined["session"]["peers"]), 2)

    def test_join_invalid_code(self):
        result = self.handler.join_session("ZZZZZZ", "u2", "Bob")
        self.assertIsNone(result)

    def test_leave_session(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        ok = self.handler.leave_session(sid, "u2")
        self.assertTrue(ok)

        # Bob's leave should generate a peer_left event for Alice
        events = self.handler.poll_events(sid, "u1")
        types = [e["type"] for e in events]
        self.assertIn("peer_left", types)

    def test_get_session_info(self):
        created = self.handler.create_session("u1", "Alice")
        info = self.handler.get_session_info(created["session_id"])
        self.assertIsNotNone(info)
        self.assertIn("presence", info)
        self.assertIn("history", info)

    def test_handle_ping(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        resp = self.handler.handle_message(sid, "u1", {"type": "ping"})
        self.assertEqual(resp["type"], "pong")

    def test_handle_cursor_move(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        self.handler.handle_message(sid, "u1", {
            "type": "cursor_move",
            "cursor": {"canvas_x": 100, "canvas_y": 200},
        })

        events = self.handler.poll_events(sid, "u2")
        cursor_events = [e for e in events if e["type"] == "cursor_update"]
        self.assertEqual(len(cursor_events), 1)
        self.assertEqual(cursor_events[0]["cursor"]["canvas_x"], 100)

    def test_handle_view_switch(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        self.handler.handle_message(sid, "u1", {"type": "view_switch", "view": "mission"})

        events = self.handler.poll_events(sid, "u2")
        view_events = [e for e in events if e["type"] == "view_update"]
        self.assertEqual(len(view_events), 1)
        self.assertEqual(view_events[0]["view"], "mission")

    def test_handle_selection(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        self.handler.handle_message(sid, "u1", {
            "type": "selection", "part_id": "rotor_1", "node_id": None,
        })

        events = self.handler.poll_events(sid, "u2")
        sel_events = [e for e in events if e["type"] == "selection_update"]
        self.assertEqual(len(sel_events), 1)
        self.assertEqual(sel_events[0]["part_id"], "rotor_1")

    def test_handle_change(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        resp = self.handler.handle_message(sid, "u1", {
            "type": "change",
            "change_type": "part_update",
            "target_id": "rotor_1",
            "data": {"size": 10},
            "before_data": {"size": 5},
        })
        self.assertEqual(resp["type"], "change_ack")
        self.assertIn("seq", resp)

        # Bob should receive the change
        events = self.handler.poll_events(sid, "u2")
        changes = [e for e in events if e["type"] == "change"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change"]["target_id"], "rotor_1")
        self.assertEqual(changes[0]["peer_name"], "Alice")

    def test_handle_chat(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        resp = self.handler.handle_message(sid, "u1", {
            "type": "chat", "text": "Hello team!",
        })
        self.assertEqual(resp["type"], "chat_ack")

        events = self.handler.poll_events(sid, "u2")
        chats = [e for e in events if e["type"] == "chat_message"]
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["message"]["text"], "Hello team!")

    def test_handle_typing(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        self.handler.handle_message(sid, "u1", {"type": "typing", "typing": True})

        events = self.handler.poll_events(sid, "u2")
        typing_events = [e for e in events if e["type"] == "typing_update"]
        self.assertEqual(len(typing_events), 1)
        self.assertTrue(typing_events[0]["typing"])

    def test_handle_undo(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]

        # Make a change first
        self.handler.handle_message(sid, "u1", {
            "type": "change",
            "change_type": "part_update",
            "target_id": "rotor_1",
            "data": {"size": 10},
            "before_data": {"size": 5},
        })

        # Then undo
        resp = self.handler.handle_message(sid, "u1", {"type": "undo"})
        self.assertEqual(resp["type"], "undo_ack")
        self.assertIsNotNone(resp["entry"])

    def test_handle_undo_empty(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        resp = self.handler.handle_message(sid, "u1", {"type": "undo"})
        self.assertEqual(resp["type"], "undo_ack")
        self.assertIsNone(resp["entry"])

    def test_conflict_broadcast(self):
        """When two peers edit the same target quickly, both should get a conflict event."""
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        # Alice edits rotor_1
        self.handler.handle_message(sid, "u1", {
            "type": "change", "change_type": "part_update",
            "target_id": "rotor_1", "data": {"size": 10},
        })
        # Drain Alice's events so far
        self.handler.poll_events(sid, "u1")
        self.handler.poll_events(sid, "u2")

        # Bob edits rotor_1 quickly after
        self.handler.handle_message(sid, "u2", {
            "type": "change", "change_type": "part_update",
            "target_id": "rotor_1", "data": {"size": 15},
        })

        # Both should get conflict notifications
        alice_events = self.handler.poll_events(sid, "u1")
        conflict_events = [e for e in alice_events if e["type"] == "conflict"]
        self.assertGreater(len(conflict_events), 0)

    def test_cleanup(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.cleanup_session(sid)
        self.assertIsNone(self.handler.get_session_info(sid))

    def test_message_to_nonexistent_session(self):
        resp = self.handler.handle_message("fake-id", "u1", {"type": "ping"})
        self.assertEqual(resp["type"], "error")

    def test_message_from_nonmember(self):
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        resp = self.handler.handle_message(sid, "intruder", {"type": "ping"})
        self.assertEqual(resp["type"], "error")

    def test_peer_joined_event(self):
        """When Bob joins, Alice should get a peer_joined event."""
        created = self.handler.create_session("u1", "Alice")
        sid = created["session_id"]
        self.handler.join_session(created["share_code"], "u2", "Bob")

        events = self.handler.poll_events(sid, "u1")
        joined = [e for e in events if e["type"] == "peer_joined"]
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]["peer"]["name"], "Bob")


if __name__ == "__main__":
    unittest.main()
