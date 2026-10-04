// The official no-render export omits a types condition. Reuse the same upstream
// provider interface rather than weakening the application boundary to any.
declare module 'ketcher-standalone/dist/binaryWasmNoRender' {
  export { StandaloneStructServiceProvider } from 'ketcher-standalone';
}
