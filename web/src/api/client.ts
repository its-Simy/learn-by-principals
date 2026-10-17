// The one typed client for the BrightLearn API: every call is checked against `paths` by path and method.
import createClient from "openapi-fetch"

import type { paths } from "@/api/types"

// Same origin: `brightlearn web` serves the app and /api together; in dev, Vite proxies /api to 8765.
export const api = createClient<paths>({ baseUrl: "" })
