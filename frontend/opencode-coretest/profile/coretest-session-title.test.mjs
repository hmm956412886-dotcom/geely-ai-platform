import assert from "node:assert/strict"
import test from "node:test"

import { coreTestSessionTitle } from "./coretest-session-title.ts"

test("localizes default OpenCode session titles", () => {
  assert.equal(coreTestSessionTitle("New session - 2026-08-06T05:30:00.000Z"), "\u65b0\u5efa\u4f1a\u8bdd")
  assert.equal(coreTestSessionTitle("Child session - 2026-08-06T05:30:00.000Z"), "\u5b50\u4f1a\u8bdd")
})

test("keeps generated and user-defined session titles", () => {
  assert.equal(coreTestSessionTitle("DBC \u62a5\u6587\u5206\u6790"), "DBC \u62a5\u6587\u5206\u6790")
  assert.equal(coreTestSessionTitle(undefined), undefined)
})
