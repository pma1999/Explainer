/* Thin wrapper: exposes router module on window for classic scripts */
import { parseRoute, buildHash, pushRoute, replaceRoute, initRouter } from './js/router.js';
window.parseRoute = parseRoute;
window.buildHash = buildHash;
window.pushRoute = pushRoute;
window.replaceRoute = replaceRoute;
window.initRouter = initRouter;
