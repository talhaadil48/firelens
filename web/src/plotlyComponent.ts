import factoryModule from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
// Vite development and production can unwrap this CommonJS package differently.
const factory = factoryModule as unknown as
  typeof factoryModule | { default: typeof factoryModule };
export default (typeof factory === "function" ? factory : factory.default)(
  Plotly,
);
