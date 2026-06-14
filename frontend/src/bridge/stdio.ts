import { spawn, type ChildProcessByStdio } from "node:child_process";
import { dirname, resolve } from "node:path";
import type { Readable, Writable } from "node:stream";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(HERE, "../../..");

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface DueCounts {
  readonly new: number;
  readonly learn: number;
  readonly review: number;
  readonly total: number;
}

export interface DeckSummary {
  readonly id: number | null;
  readonly name: string;
  readonly due: DueCounts;
  readonly totalDue: number;
}

export interface SessionSummary {
  readonly deck: string;
  readonly label: string;
  readonly cardCount: number;
  readonly durationSeconds: number;
  readonly timestampEpoch: number;
}

export interface HomeState {
  readonly version: string;
  readonly backendName: string;
  readonly format: string;
  readonly deckContext: string;
  readonly due: DueCounts;
  readonly decks: readonly DeckSummary[];
  readonly recentSessions: readonly SessionSummary[];
  readonly streak: number;
  readonly sync: {
    readonly state: string;
    readonly label: string;
  };
}

export type NavigateTarget = "review" | "browse" | "add" | "stats";

export interface AppRunCommandResult {
  readonly statusMessage: string;
  readonly navigate: NavigateTarget | null;
  readonly home: HomeState | null;
}

interface RpcSuccess<T> {
  readonly jsonrpc: "2.0";
  readonly id: number | string | null;
  readonly result: T;
}

interface RpcFailure {
  readonly jsonrpc: "2.0";
  readonly id: number | string | null;
  readonly error: {
    readonly code: number;
    readonly message: string;
    readonly data?: Record<string, unknown>;
  };
}

interface RpcRequest {
  readonly jsonrpc: "2.0";
  readonly id: number;
  readonly method: string;
  readonly params: Record<string, JsonValue>;
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

export class StdioRpcClient {
  private readonly child: ChildProcessByStdio<Writable, Readable, null>;
  private readonly pending = new Map<number, PendingRequest>();
  private nextId = 1;
  private buffer = "";
  private closed = false;

  constructor(extraArgs: readonly string[] = []) {
    this.child = spawn(
      "uv",
      ["run", "python", "-m", "anki_cli.frontend_api.serve", ...extraArgs],
      {
        cwd: PROJECT_ROOT,
        stdio: ["pipe", "pipe", "inherit"],
        env: process.env,
      },
    );

    this.child.stdout.setEncoding("utf8");

    this.child.stdout.on("data", (chunk: string | Buffer) => {
      this.onStdout(String(chunk));
    });

    this.child.once("error", (error) => {
      this.rejectAll(new Error(`Failed to start RPC server: ${error.message}`));
    });

    this.child.once("exit", (code, signal) => {
      this.closed = true;
      this.rejectAll(
        new Error(`RPC server exited unexpectedly (code=${code}, signal=${signal})`),
      );
    });
  }

  async request<T>(
    method: string,
    params: Record<string, JsonValue> = {},
  ): Promise<T> {
    if (this.closed) {
      throw new Error("RPC server is not running");
    }

    const id = this.nextId++;
    const payload: RpcRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    return await new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
      });

      const encoded = `${JSON.stringify(payload)}\n`;
      this.child.stdin.write(encoded, "utf8", (error) => {
        if (error) {
          this.pending.delete(id);
          reject(error);
        }
      });
    });
  }

  dispose(): void {
    if (this.closed) {
      return;
    }

    this.closed = true;
    this.child.stdin.end();
    this.child.kill("SIGTERM");
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk;

    while (true) {
      const newlineIndex = this.buffer.indexOf("\n");
      if (newlineIndex < 0) {
        return;
      }

      const line = this.buffer.slice(0, newlineIndex).trim();
      this.buffer = this.buffer.slice(newlineIndex + 1);

      if (!line) {
        continue;
      }

      this.handleLine(line);
    }
  }

  private handleLine(line: string): void {
    let message: RpcSuccess<unknown> | RpcFailure;

    try {
      message = JSON.parse(line) as RpcSuccess<unknown> | RpcFailure;
    } catch (error) {
      this.rejectAll(
        new Error(
          `RPC server returned invalid JSON: ${
            error instanceof Error ? error.message : String(error)
          }`,
        ),
      );
      return;
    }

    if (typeof message.id !== "number") {
      return;
    }

    const pending = this.pending.get(message.id);
    if (!pending) {
      return;
    }

    this.pending.delete(message.id);

    if ("result" in message) {
      pending.resolve(message.result);
      return;
    }

    const details =
      typeof message.error.data?.details === "string"
        ? `: ${message.error.data.details}`
        : "";

    pending.reject(
      new Error(`${message.error.message}${details}`),
    );
  }

  private rejectAll(error: Error): void {
    for (const entry of this.pending.values()) {
      entry.reject(error);
    }
    this.pending.clear();
  }
}