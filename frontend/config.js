/* FE/BE 분리 — API 요청 라우팅.
 *
 * 프론트엔드와 API 를 같은 서버가 서빙하면 API_BASE_URL 을 "" 로 두면 된다(기본값,
 * FastAPI 가 /static 으로 프론트를 마운트하는 경우).
 *
 * S3/CloudFront 같은 정적 호스팅에 올릴 때는 아래 셋 중 하나로 백엔드 주소를 지정한다:
 *   1) 이 파일 상단의 DEFAULT_API_BASE_URL 값을 배포 시 치환
 *   2) index.html 에서 <script>window.API_BASE_URL="https://api.example.com"</script>
 *   3) URL 에 ?api=https://api.example.com  (localStorage 에 저장되어 유지됨)
 *
 * 지정되면 /auth /market /chat /ingest /backtests /health /learning 로 시작하는
 * fetch 요청을 그 오리진으로 보낸다.
 */
(function () {
  var DEFAULT_API_BASE_URL = ""; // ← 배포 파이프라인에서 여기를 치환

  var params = new URLSearchParams(location.search);
  var override = params.get("api");
  if (override != null) {
    try { localStorage.setItem("API_BASE_URL", override); } catch (e) {}
  }

  var base =
    (window.API_BASE_URL != null && window.API_BASE_URL !== "")
      ? window.API_BASE_URL
      : (override
         || safeGet("API_BASE_URL")
         || DEFAULT_API_BASE_URL
         || "");
  base = String(base).replace(/\/+$/, "");
  window.API_BASE_URL = base;
  if (!base) return;

  var API_PREFIXES = [
    "/auth/", "/market/", "/chat", "/ingest",
    "/backtests", "/health", "/learning/",
  ];
  function isApiPath(p) {
    for (var i = 0; i < API_PREFIXES.length; i++) {
      if (p === API_PREFIXES[i] || p.indexOf(API_PREFIXES[i]) === 0) return true;
    }
    return false;
  }
  function safeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  var origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      if (typeof input === "string" && input.charAt(0) === "/" && isApiPath(input)) {
        input = base + input;
      } else if (input && typeof input === "object" &&
                 typeof input.url === "string" &&
                 input.url.charAt(0) === "/" && isApiPath(input.url)) {
        input = new Request(base + input.url, input);
      }
    } catch (e) { /* fall through to original */ }
    return origFetch(input, init);
  };
})();
