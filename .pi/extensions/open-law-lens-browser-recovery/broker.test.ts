import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ALLOWED_PRESS_KEYS,
  ALLOWED_TOOLS,
  authorizeWindow,
  decideTool,
  initialBrokerState,
  isScholarUrl,
  normalizeKey,
} from "./broker.ts";

function authorizedState() {
  const state = initialBrokerState();
  const error = authorizeWindow(state, 101, "In re Caden C. - Google Scholar", "https://scholar.google.com/scholar_case?case=1");
  assert.equal(error, "");
  return state;
}

test("forbidden tools are denied regardless of state", () => {
  const state = authorizedState();
  state.fresh = true;
  for (const tool of ["screenshot", "click", "type_text", "scroll", "drag", "set_value", "move_window", "resize_window", "activate_window", "list_apps"]) {
    assert.equal(decideTool(state, tool, {}), "deny", tool);
  }
});

test("allowlist is exactly the six desktop tools", () => {
  assert.deepEqual(
    [...ALLOWED_TOOLS].sort(),
    ["doctor", "focused_window", "get_app_state", "list_windows", "perform_action", "press_key"].sort(),
  );
});

test("read-only tools are allowed without authorization", () => {
  const state = initialBrokerState();
  for (const tool of ["doctor", "list_windows", "focused_window"]) {
    assert.equal(decideTool(state, tool, {}), "allow_once", tool);
  }
});

test("get_app_state requires an exact numeric window_id", () => {
  const state = initialBrokerState();
  assert.equal(decideTool(state, "get_app_state", { max_nodes: 100 }), "deny");
  assert.equal(decideTool(state, "get_app_state", { window_id: "101", max_nodes: 100 }), "deny");
  assert.equal(decideTool(state, "get_app_state", { window_id: 101, max_nodes: 100 }), "allow_once");
});

test("get_app_state omits screenshots and rejects app-id targeting", () => {
  const state = initialBrokerState();
  assert.equal(
    decideTool(state, "get_app_state", { window_id: 101, max_nodes: 100, include_screenshot: true }),
    "deny",
  );
  assert.equal(
    decideTool(state, "get_app_state", { app_id: "firefox", max_nodes: 100 }),
    "deny",
  );
  assert.equal(
    decideTool(state, "get_app_state", { window_id: 101, app_id: "firefox", max_nodes: 100 }),
    "deny",
  );
});

test("get_app_state stays within a bounded node count", () => {
  const state = initialBrokerState();
  assert.equal(decideTool(state, "get_app_state", { window_id: 101 }), "deny");
  assert.equal(decideTool(state, "get_app_state", { window_id: 101, max_nodes: 0 }), "deny");
  assert.equal(decideTool(state, "get_app_state", { window_id: 101, max_nodes: 10000 }), "deny");
  assert.equal(decideTool(state, "get_app_state", { window_id: 101, max_nodes: 1000 }), "allow_once");
});

test("perform_action is denied before authorization or without freshness", () => {
  const state = initialBrokerState();
  assert.equal(decideTool(state, "perform_action", { element_index: 0 }), "deny");
  const authorized = authorizedState();
  assert.equal(decideTool(authorized, "perform_action", { element_index: 0 }), "deny");
});

test("perform_action requires element_index and rejects action overrides", () => {
  const state = authorizedState();
  state.fresh = true;
  assert.equal(decideTool(state, "perform_action", {}), "deny");
  assert.equal(decideTool(state, "perform_action", { element_index: 1, action: "press" }), "deny");
  assert.equal(decideTool(state, "perform_action", { element_index: 1, element_identifier: "a" }), "deny");
  assert.equal(decideTool(state, "perform_action", { element_index: 1, name: "x" }), "deny");
  assert.equal(decideTool(state, "perform_action", { element_index: 1 }), "allow_once");
});

test("mutating calls consume freshness requiring a re-observation", () => {
  const state = authorizedState();
  state.fresh = true;
  assert.equal(decideTool(state, "perform_action", { element_index: 1 }), "allow_once");
  assert.equal(decideTool(state, "perform_action", { element_index: 1 }), "deny");
  // Re-observe the authorized window grants freshness again.
  assert.equal(
    decideTool(state, "get_app_state", { window_id: 101, max_nodes: 500 }),
    "allow_once",
  );
  assert.equal(decideTool(state, "perform_action", { element_index: 2 }), "allow_once");
});

test("press_key allows only ctrl+a and ctrl+c on the authorized window", () => {
  const state = authorizedState();
  state.fresh = true;
  assert.equal(decideTool(state, "press_key", { window_id: 101, key: "ctrl+a" }), "allow_once");

  state.fresh = true;
  assert.equal(decideTool(state, "press_key", { window_id: 101, key: "Ctrl+C" }), "allow_once");

  state.fresh = true;
  assert.equal(decideTool(state, "press_key", { window_id: 101, key: "ctrl+v" }), "deny");

  state.fresh = true;
  assert.equal(decideTool(state, "press_key", { window_id: 999, key: "ctrl+a" }), "deny");

  state.fresh = true;
  assert.equal(decideTool(state, "press_key", { key: "ctrl+a" }), "deny");
});

test("authorization replacement overwrites the prior window", () => {
  const state = authorizedState();
  assert.equal(state.authorized?.windowId, 101);
  const error = authorizeWindow(state, 202, "Another v. Case - Google Scholar", "https://scholar.google.com/scholar_case?case=2");
  assert.equal(error, "");
  assert.equal(state.authorized?.windowId, 202);
  assert.equal(state.fresh, false);
});

test("authorizeWindow rejects non-scholar urls and empty titles", () => {
  const state = initialBrokerState();
  assert.notEqual(authorizeWindow(state, 101, "A v. B", "https://example.com/opinion"), "");
  assert.equal(state.authorized, null);
  assert.notEqual(authorizeWindow(state, 101, "   ", "https://scholar.google.com/scholar_case?case=1"), "");
  assert.equal(state.authorized, null);
  assert.notEqual(authorizeWindow(state, "101", "A v. B", "https://scholar.google.com/scholar_case?case=1"), "");
  assert.equal(state.authorized, null);
});

test("isScholarUrl and normalizeKey helpers", () => {
  assert.equal(isScholarUrl("https://scholar.google.com/scholar_case?case=1"), true);
  assert.equal(isScholarUrl("http://scholar.google.com/scholar_case?case=1"), false);
  assert.equal(isScholarUrl("https://example.com/scholar_case?case=1"), false);
  assert.equal(isScholarUrl("not a url"), false);
  assert.equal(normalizeKey("Ctrl+A"), "ctrl+a");
  assert.equal(normalizeKey("Ctrl-A"), "ctrl+a");
  assert.equal(normalizeKey("ctrl + c"), "ctrl+c");
  assert.equal(normalizeKey(123), "");
});

test("press_key key allowlist matches ctrl+a and ctrl+c only", () => {
  assert.deepEqual([...ALLOWED_PRESS_KEYS].sort(), ["ctrl+a", "ctrl+c"]);
});
