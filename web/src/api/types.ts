/**
 * Hand-written stand-in for the generated API types, covering only GET /api/health.
 * Replaced by `pnpm gen` (openapi-typescript openapi.json -o src/api/types.ts) once the API
 * and web/openapi.json land; the shape below matches what openapi-typescript emits.
 */

export interface paths {
  "/api/health": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get: {
      parameters: {
        query?: never
        header?: never
        path?: never
        cookie?: never
      }
      requestBody?: never
      responses: {
        /** @description The API is up. */
        200: {
          headers: {
            [name: string]: unknown
          }
          content: {
            "application/json": components["schemas"]["HealthOut"]
          }
        }
      }
    }
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}

export type webhooks = Record<string, never>

export interface components {
  schemas: {
    HealthOut: {
      ok: boolean
      version: string
      schema_version: number
    }
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}

export type $defs = Record<string, never>

export type operations = Record<string, never>
