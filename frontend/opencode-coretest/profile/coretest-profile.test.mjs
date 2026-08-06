import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"

const css = readFileSync(new URL("./coretest-profile.css", import.meta.url), "utf8")

test("hides project management for the registered CoreTest workspace", () => {
  assert.match(css, /data-action="home-add-project"/)
  assert.match(css, /data-action="home-add-project-row"/)
  assert.match(css, /data-action="home-project-menu"/)
})

test("keeps OpenCode native new session controls", () => {
  assert.doesNotMatch(css, /aria-label="New session"/)
  assert.doesNotMatch(css, /opencode-v2-icon-plus/)
  assert.doesNotMatch(css, /data-action="home-new-session"/)
  assert.doesNotMatch(css, /data-action="home-project-new-session"/)
})
