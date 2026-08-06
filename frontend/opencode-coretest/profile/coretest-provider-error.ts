function providerErrorKind(message: string) {
  const text = message.trim().toLowerCase()

  if (
    text.includes("upstream service temporarily unavailable") ||
    text.includes("service temporarily unavailable") ||
    text.includes("service unavailable") ||
    /\b(?:502|503|504)\b/.test(text)
  ) {
    return "unavailable"
  }
  if (text.includes("rate limit") || text.includes("too many requests") || /\b429\b/.test(text)) {
    return "rateLimit"
  }
  if (text.includes("timeout") || text.includes("timed out")) return "timeout"
  if (
    text.includes("unauthorized") ||
    text.includes("invalid api key") ||
    text.includes("authentication") ||
    /\b(?:401|403)\b/.test(text)
  ) {
    return "authentication"
  }
  return "unknown"
}

export function coreTestProviderRetry(message: string) {
  const kind = providerErrorKind(message)
  if (kind === "unavailable") return "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528"
  if (kind === "rateLimit") return "\u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41"
  if (kind === "timeout") return "\u6a21\u578b\u670d\u52a1\u54cd\u5e94\u8d85\u65f6"
  if (kind === "authentication") return "\u6a21\u578b API \u9a8c\u8bc1\u5931\u8d25"
  return "\u6a21\u578b\u8c03\u7528\u6682\u65f6\u5931\u8d25"
}

export function coreTestProviderError(message: string) {
  const kind = providerErrorKind(message)
  if (kind === "unavailable") {
    return "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u672c\u8f6e\u5df2\u505c\u6b62\u3002\u8bf7\u7a0d\u540e\u6062\u590d\u4efb\u52a1\u5e76\u91cd\u65b0\u53d1\u9001\u3002"
  }
  if (kind === "rateLimit") {
    return "\u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41\uff0c\u672c\u8f6e\u5df2\u505c\u6b62\u3002\u8bf7\u7a0d\u540e\u6062\u590d\u4efb\u52a1\u5e76\u91cd\u65b0\u53d1\u9001\u3002"
  }
  if (kind === "timeout") {
    return "\u6a21\u578b\u670d\u52a1\u54cd\u5e94\u8d85\u65f6\uff0c\u672c\u8f6e\u5df2\u505c\u6b62\u3002\u8bf7\u7a0d\u540e\u6062\u590d\u4efb\u52a1\u5e76\u91cd\u65b0\u53d1\u9001\u3002"
  }
  if (kind === "authentication") {
    return "\u6a21\u578b API \u9a8c\u8bc1\u5931\u8d25\u3002\u8bf7\u68c0\u67e5 API Key\u3001Base URL \u548c\u6a21\u578b\u540d\u3002"
  }
  return "\u6a21\u578b\u8c03\u7528\u5931\u8d25\uff0c\u672c\u8f6e\u5df2\u505c\u6b62\u3002\u8bf7\u68c0\u67e5\u6a21\u578b API \u914d\u7f6e\u6216\u7a0d\u540e\u91cd\u8bd5\u3002"
}
