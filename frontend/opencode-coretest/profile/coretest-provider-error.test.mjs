import assert from "node:assert/strict"
import test from "node:test"

import { coreTestProviderError, coreTestProviderRetry } from "./coretest-provider-error.ts"

test("localizes transient upstream failures", () => {
  assert.equal(
    coreTestProviderError('"Upstream service temporarily unavailable"'),
    "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u672c\u8f6e\u5df2\u505c\u6b62\u3002\u8bf7\u7a0d\u540e\u6062\u590d\u4efb\u52a1\u5e76\u91cd\u65b0\u53d1\u9001\u3002",
  )
  assert.match(coreTestProviderError("HTTP 503"), /^\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528/)
})

test("localizes rate limits, timeouts, and authentication failures", () => {
  assert.match(coreTestProviderError("429 Too Many Requests"), /\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41/)
  assert.match(coreTestProviderError("request timed out"), /\u54cd\u5e94\u8d85\u65f6/)
  assert.match(coreTestProviderError("401 invalid API key"), /API \u9a8c\u8bc1\u5931\u8d25/)
})

test("does not expose unknown provider text", () => {
  const result = coreTestProviderError("vendor-internal-error")
  assert.doesNotMatch(result, /vendor-internal-error/)
  assert.match(result, /^\u6a21\u578b\u8c03\u7528\u5931\u8d25/)
})

test("localizes retry reasons without claiming the task stopped", () => {
  assert.equal(coreTestProviderRetry("Service temporarily unavailable"), "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528")
  assert.equal(coreTestProviderRetry("429 Too Many Requests"), "\u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41")
  assert.doesNotMatch(coreTestProviderRetry("vendor-internal-error"), /vendor-internal-error/)
})
