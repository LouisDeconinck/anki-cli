import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import {
  StdioRpcClient,
  type AppRunCommandResult,
  type DeckSummary,
  type HomeState,
} from "./bridge/stdio";

const COLORS = {
  bg: "#0d0f14",
  panel: "#111318",
  panelAlt: "#161820",
  edge: "#2a2f45",
  edgeSoft: "#202538",
  inputEdge: "#355a90",
  text: "#cdd4e6",
  dim: "#556070",
  muted: "#2d3548",
  blue: "#74b8ff",
  blueSoft: "#4d9ef8",
  green: "#44c76a",
  orange: "#f0a040",
  red: "#e85858",
} as const;

const COLUMN_WIDTH = 82;
const DUE_TILE_WIDTH = 23;
const DUE_TILE_HEIGHT = 6;
const DUE_STRIP_WIDTH = DUE_TILE_WIDTH * 3 + 2;
const DECK_CARD_WIDTH = 18;
const SHORTCUT_WIDTH = 10;

export function App() {
  const client = useMemo(() => new StdioRpcClient(), []);
  const [home, setHome] = useState<HomeState | null>(null);
  const [statusMessage, setStatusMessage] = useState("Connecting...");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [commandDraft, setCommandDraft] = useState("");
  const [inputKey, setInputKey] = useState(0);

  const loadHome = useCallback(async () => {
    try {
      const next = await client.request<HomeState>("home.state");
      setHome(next);
      setStatusMessage(`Connected to ${next.backendName} backend`);
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(asErrorMessage(error));
    }
  }, [client]);

  useEffect(() => {
    void loadHome();

    return () => {
      client.dispose();
    };
  }, [client, loadHome]);

  const handleSubmit = useCallback(async () => {
    const line = commandDraft.trim();
    if (!line) {
      return;
    }

    try {
      const result = await client.request<AppRunCommandResult>("app.run_command", {
        line,
      });

      if (result.home) {
        setHome(result.home);
      }

      if (result.navigate) {
        setStatusMessage(`${result.statusMessage} (router not wired yet)`);
      } else {
        setStatusMessage(result.statusMessage);
      }
    } catch (error) {
      setStatusMessage(asErrorMessage(error));
    } finally {
      setCommandDraft("");
      setInputKey((value) => value + 1);
    }
  }, [client, commandDraft]);

  if (errorMessage) {
    return (
      <ScreenFrame>
        <box
          style={{
            width: 76,
            border: true,
            backgroundColor: COLORS.panel,
            padding: 2,
            flexDirection: "column",
            gap: 1,
          }}
        >
          <text fg={COLORS.red}>Failed to load home state</text>
          <text fg={COLORS.text}>{errorMessage}</text>
        </box>
      </ScreenFrame>
    );
  }

  if (!home) {
    return (
      <ScreenFrame>
        <text fg={COLORS.text}>Loading...</text>
      </ScreenFrame>
    );
  }

  return (
    <box
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: COLORS.bg,
        flexDirection: "column",
      }}
    >
      <box
        style={{
          flexGrow: 1,
          alignItems: "center",
          justifyContent: "flex-start",
          padding: 1,
        }}
      >
        <box
          style={{
            width: COLUMN_WIDTH,
            flexDirection: "column",
            gap: 2,
          }}
        >
          <Hero home={home} />

          <box
            style={{
              width: "100%",
              flexDirection: "row",
              justifyContent: "center",
            }}
          >
            <DueStrip due={home.due} />
          </box>

          <box style={{ width: "100%", flexDirection: "column", gap: 1 }}>
            <SectionHeader title="RECENT DECKS" rightLabel="all decks ->" />
            {home.decks.length > 0 ? (
              <box
                style={{
                  width: "100%",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 2,
                }}
              >
                {home.decks.slice(0, 4).map((deck) => (
                  <DeckCard key={deck.name} deck={deck} />
                ))}
              </box>
            ) : (
              <text fg={COLORS.dim}>No decks found.</text>
            )}
          </box>

          <box style={{ width: "100%", flexDirection: "column", gap: 1 }}>
            <SectionHeader title="QUICK ACTIONS" />
            <Panel>
              <box style={{ width: "100%", flexDirection: "column", gap: 1 }}>
                <ActionRow
                  icon=">"
                  command="/study"
                  description="Start reviewing due cards"
                  shortcut="ctrl+s"
                  primary={true}
                />
                <ActionRow
                  icon="="
                  command="/browse"
                  description="Search and manage cards"
                  shortcut="ctrl+b"
                />
                <ActionRow
                  icon="+"
                  command="/add"
                  description="Create a new card"
                  shortcut="ctrl+n"
                />
                <ActionRow
                  icon="*"
                  command="/stats"
                  description="View statistics and heatmap"
                  shortcut="ctrl+t"
                />
              </box>
            </Panel>
          </box>

          <box style={{ width: "100%", flexDirection: "column", gap: 1 }}>
            <box
              style={{
                width: "100%",
                border: true,
                borderColor: COLORS.inputEdge,
                backgroundColor: COLORS.panel,
                padding: 1,
                flexDirection: "row",
                alignItems: "center",
                gap: 1,
              }}
            >
              <text fg={COLORS.blue}>{">"}</text>

              <box style={{ flexGrow: 1 }}>
                <input
                  key={inputKey}
                  placeholder="Type a command or / for suggestions..."
                  focused={true}
                  onInput={(value) => setCommandDraft(value)}
                  onSubmit={handleSubmit}
                />
              </box>

              <Pill label="tab" />
            </box>

            <text fg={COLORS.dim}>{statusMessage}</text>

            <box
              style={{
                width: "100%",
                flexDirection: "row",
                justifyContent: "center",
                gap: 1,
              }}
            >
              <HintChip keyLabel="up/down" text="history" />
              <HintChip keyLabel="Tab" text="autocomplete" />
              <HintChip keyLabel="ctrl+r" text="refresh" />
              <HintChip keyLabel="ctrl+c" text="quit" />
            </box>
          </box>
        </box>
      </box>

      <Footer home={home} />
    </box>
  );
}

function ScreenFrame(props: { children: ReactNode }) {
  return (
    <box
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: COLORS.bg,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {props.children}
    </box>
  );
}

function Hero(props: { home: HomeState }) {
  return (
    <box
      style={{
        width: "100%",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 1,
        padding: 1,
      }}
    >
      <ascii-font
        text="anki-cli"
        font="tiny"
        color={COLORS.blueSoft}
        selectable={false}
      />
      <text fg={COLORS.muted}>v {props.home.version} . spaced repetition</text>
    </box>
  );
}

function SectionHeader(props: { title: string; rightLabel?: string }) {
  return (
    <box style={{ width: "100%", flexDirection: "row" }}>
      <box style={{ flexGrow: 1 }}>
        <text fg={COLORS.dim}>{props.title}</text>
      </box>
      {props.rightLabel ? <text fg={COLORS.blue}>{props.rightLabel}</text> : null}
    </box>
  );
}

function Panel(props: { children: ReactNode }) {
  return (
    <box
      style={{
        width: "100%",
        border: true,
        borderColor: COLORS.edge,
        backgroundColor: COLORS.panel,
        padding: 1,
      }}
    >
      {props.children}
    </box>
  );
}

function DueStrip(props: { due: HomeState["due"] }) {
  return (
    <box
      style={{
        width: DUE_STRIP_WIDTH,
        height: DUE_TILE_HEIGHT,
        flexDirection: "row",
      }}
    >
      <DueTile
        label="NEW"
        value={props.due.new}
        color={COLORS.blueSoft}
        showLeftEdge={true}
      />
      <box style={{ width: 1, backgroundColor: COLORS.edge }} />
      <DueTile label="LEARNING" value={props.due.learn} color={COLORS.orange} />
      <box style={{ width: 1, backgroundColor: COLORS.edge }} />
      <DueTile
        label="REVIEW"
        value={props.due.review}
        color={COLORS.green}
        showRightEdge={true}
      />
    </box>
  );
}

function DueTile(props: {
  label: string;
  value: number;
  color: string;
  showLeftEdge?: boolean;
  showRightEdge?: boolean;
}) {
  return (
    <box
      style={{
        width: DUE_TILE_WIDTH,
        height: DUE_TILE_HEIGHT,
        backgroundColor: COLORS.panel,
        flexDirection: "column",
      }}
    >
      <box style={{ width: "100%", height: 1, backgroundColor: props.color }} />
      <box
        style={{
          flexGrow: 1,
          flexDirection: "row",
        }}
      >
        {props.showLeftEdge ? <box style={{ width: 1, backgroundColor: COLORS.edge }} /> : null}
        <box
          style={{
            flexGrow: 1,
            backgroundColor: COLORS.panel,
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 0,
          }}
        >
          <text>
            <strong>
              <span fg={props.color}>{String(props.value)}</span>
            </strong>
          </text>
          <text>
            <span fg={COLORS.muted}>{props.label}</span>
          </text>
        </box>
        {props.showRightEdge ? <box style={{ width: 1, backgroundColor: COLORS.edge }} /> : null}
      </box>
      <box style={{ width: "100%", height: 1, backgroundColor: COLORS.edge }} />
    </box>
  );
}

function DeckCard(props: { deck: DeckSummary }) {
  return (
    <box
      style={{
        width: DECK_CARD_WIDTH,
        height: 4,
        border: true,
        borderColor: COLORS.edge,
        backgroundColor: COLORS.panelAlt,
        padding: 1,
        flexDirection: "column",
        gap: 1,
      }}
    >
      <text fg={COLORS.text}>{truncate(props.deck.name, 15)}</text>
      <box style={{ flexDirection: "row", gap: 1 }}>
        <text fg={COLORS.blueSoft}>{props.deck.due.new}n</text>
        <text fg={COLORS.orange}>{props.deck.due.learn}l</text>
        <text fg={COLORS.green}>{props.deck.due.review}r</text>
      </box>
    </box>
  );
}

function ActionRow(props: {
  icon: string;
  command: string;
  description: string;
  shortcut: string;
  primary?: boolean;
}) {
  return (
    <box
      style={{
        width: "100%",
        flexDirection: "row",
        alignItems: "center",
        gap: 2,
      }}
    >
      <text fg={COLORS.dim}>{props.icon}</text>

      <box style={{ width: 12 }}>
        <text fg={props.primary ? COLORS.blue : COLORS.blueSoft}>{props.command}</text>
      </box>

      <box style={{ flexGrow: 1 }}>
        <text fg={COLORS.dim}>{props.description}</text>
      </box>

      <box style={{ width: SHORTCUT_WIDTH, alignItems: "flex-end" }}>
        <Pill label={props.shortcut} />
      </box>
    </box>
  );
}

function HintChip(props: { keyLabel: string; text: string }) {
  return (
    <box
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 1,
      }}
    >
      <Pill label={props.keyLabel} />
      <text fg={COLORS.dim}>{props.text}</text>
    </box>
  );
}

function Pill(props: { label: string; color?: string }) {
  return (
    <box
      style={{
        border: true,
        borderColor: COLORS.edgeSoft,
        backgroundColor: COLORS.panelAlt,
        padding: 0,
      }}
    >
      <text fg={props.color ?? COLORS.muted}>{props.label}</text>
    </box>
  );
}

function Footer(props: { home: HomeState }) {
  return (
    <box
      style={{
        width: "100%",
        flexDirection: "column",
      }}
    >
      <box style={{ width: "100%", height: 1, backgroundColor: COLORS.edgeSoft }} />
      <box
        style={{
          width: "100%",
          backgroundColor: COLORS.panel,
          padding: 1,
          flexDirection: "row",
        }}
      >
        <box style={{ flexGrow: 1, flexDirection: "row", gap: 2 }}>
          <text fg={COLORS.dim}>backend {props.home.backendName}</text>
          <text fg={COLORS.dim}>format {props.home.format}</text>
          <text fg={COLORS.dim}>deck {props.home.deckContext}</text>
        </box>

        <box style={{ flexDirection: "row", gap: 2 }}>
          {props.home.streak > 0 ? (
            <text fg={COLORS.orange}>streak {props.home.streak}d</text>
          ) : null}
          <text fg={props.home.sync.state === "up_to_date" ? COLORS.green : COLORS.red}>
            sync {props.home.sync.label}
          </text>
        </box>
      </box>
    </box>
  );
}

function truncate(value: string, max: number): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1)}…`;
}

function asErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}