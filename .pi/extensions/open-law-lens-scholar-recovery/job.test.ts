import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildLaunchCommand,
  buildResult,
  completionError,
  isScholarCaseUrl,
  launchQueryError,
  normalizeQuery,
  RESULT_VERSION,
} from "./job.ts";

test("isScholarCaseUrl accepts only https scholar_case URLs", () => {
  assert.equal(isScholarCaseUrl("https://scholar.google.com/scholar_case?case=1"), true);
  assert.equal(isScholarCaseUrl("https://www.scholar.google.com/scholar_case?case=1"), true);
  assert.equal(isScholarCaseUrl("http://scholar.google.com/scholar_case?case=1"), false);
  assert.equal(isScholarCaseUrl("https://scholar.google.com/scholar?q=x"), false);
  assert.equal(isScholarCaseUrl("https://example.com/scholar_case?case=1"), false);
  assert.equal(isScholarCaseUrl("not a url"), false);
  assert.equal(isScholarCaseUrl(123), false);
});

test("launchQueryError rejects a query differing from the bound request", () => {
  assert.equal(launchQueryError("11 Cal.5th 614", "11 Cal.5th 614"), "");
  assert.equal(launchQueryError("In re Caden C.", "In re Caden C."), "");
  assert.notEqual(launchQueryError("11 Cal.5th 614", "12 Cal.5th 614"), "");
  assert.notEqual(launchQueryError("11 Cal.5th 614", ""), "");
  assert.notEqual(launchQueryError("", "11 Cal.5th 614"), "");
});

test("buildLaunchCommand uses uv argv execution without a shell", () => {
  const { command, args } = buildLaunchCommand("11 Cal.5th 614", "/src/open-law-lens", "/usr/bin/uv");
  assert.equal(command, "/usr/bin/uv");
  assert.deepEqual(args, [
    "run",
    "--project",
    "/src/open-law-lens",
    "--no-sync",
    "open-law-lens",
    "open-scholar-browser",
    "11 Cal.5th 614",
  ]);
});

test("buildLaunchCommand falls back to uv when no explicit binary", () => {
  const { command } = buildLaunchCommand("query", "/src", "");
  assert.equal(command, "uv");
});

test("completionError requires a valid outcome and message", () => {
  assert.equal(completionError({ outcome: "copied", source_url: "https://scholar.google.com/scholar_case?case=1", message: "ok" }), null);
  assert.equal(completionError({ outcome: "not_found", message: "no matches" }), null);
  assert.notEqual(completionError({ outcome: "bogus", message: "x" }), null);
  assert.notEqual(completionError({ outcome: "copied", message: "x" }), null);
  assert.notEqual(completionError({ outcome: "copied", source_url: "https://example.com/x", message: "x" }), null);
});

test("completionError requires a Scholar case URL only for copied", () => {
  assert.notEqual(completionError({ outcome: "copied", source_url: "https://scholar.google.com/scholar?q=x", message: "x" }), null);
  assert.equal(completionError({ outcome: "blocked", message: "captcha" }), null);
});

test("buildResult normalizes into the fixed result contract", () => {
  const result = buildResult({ outcome: "copied", query: "  11  Cal.5th 614 ", source_url: "https://scholar.google.com/scholar_case?case=1", message: " found " });
  assert.deepEqual(result, {
    version: RESULT_VERSION,
    outcome: "copied",
    query: "11 Cal.5th 614",
    source_url: "https://scholar.google.com/scholar_case?case=1",
    message: "found",
  });
  const failed = buildResult({ outcome: "failed", query: "x", message: "no pi" });
  assert.equal(failed.source_url, "");
});

test("normalizeQuery collapses whitespace", () => {
  assert.equal(normalizeQuery("  In   re\tCaden  "), "In re Caden");
  assert.equal(normalizeQuery(42), "");
});
