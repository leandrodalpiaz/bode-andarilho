/// <reference types="vite/client" />

interface HCaptchaApi {
  render: (container: HTMLElement, options: {
    sitekey: string;
    callback: (token: string) => void;
    "expired-callback"?: () => void;
    "error-callback"?: () => void;
  }) => number;
  reset: (widgetId?: number) => void;
}

interface Window {
  hcaptcha?: HCaptchaApi;
}
