import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, Config, Evidence, Framework, Session, Signal } from "./api";

type Focus = { turn: number; start: number; end: number } | null;

export default function App() {
  const [fw, setFw] = useState<Framework | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [code, setCode] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.framework().then(setFw).catch((e) => setError(e.message));
    api.config().then(setCfg).catch(() => undefined);
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [session?.turns.length]);

  const run = async (fn: () => Promise<Session>) => {
    setBusy(true);
    setError(null);
    try {
      setSession(await fn());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const participantCount = session?.turns.filter((t) => t.role === "participant").length ?? 0;
  const active = session?.status === "active";
  const scored = session?.status === "scored";

  const submit = () => {
    const text = draft.trim();
    if (!session || !text || busy) return;
    setDraft("");
    run(() => api.answer(session.id, text));
  };

  // every evidence span, so the transcript can highlight it
  const spans = useMemo(() => {
    const m = new Map<number, Evidence[]>();
    session?.signals.forEach((s) =>
      s.evidence.forEach((e) => {
        if (e.turn_index == null || e.start == null) return;
        m.set(e.turn_index, [...(m.get(e.turn_index) ?? []), e]);
      })
    );
    return m;
  }, [session?.signals]);

  if (!session) {
    return (
      <main className="start">
        <h1>Signal Event</h1>
        <p className="lede">
          A short structured interview. Answer in your own words. Afterwards, each score is shown next to
          the exact words that support it, and a dimension without enough evidence is left unscored.
        </p>
        {fw && (
          <p className="meta">
            {fw.title}. {fw.max_turns} questions, about five minutes.
          </p>
        )}
        {cfg?.access_code_required && (
          <div className="field">
            <label htmlFor="code">Access code</label>
            <input id="code" type="password" value={code} autoComplete="off"
                   onChange={(e) => setCode(e.target.value)} />
          </div>
        )}
        <button className="primary" disabled={busy || !fw || (cfg?.access_code_required && !code)}
                onClick={() => run(() => api.start(code))}>
          Start interview
        </button>
        {error && <p className="error" role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <div className={`layout ${scored ? "with-results" : ""}`}>
      <section className="transcript" aria-label="Interview transcript">
        <header>
          <h1>{fw?.title ?? "Interview"}</h1>
          {active && (
            <span className="progress">
              Answer {Math.min(participantCount + 1, fw?.max_turns ?? 5)} of {fw?.max_turns ?? 5}
            </span>
          )}
        </header>

        <ol className="turns">
          {session.turns.map((t) => (
            <li key={t.index} className={t.role}>
              <span className="who">{t.role === "interviewer" ? "Interviewer" : "You"}</span>
              <p>
                <Highlighted
                  text={t.text}
                  spans={spans.get(t.index) ?? []}
                  focus={focus?.turn === t.index ? focus : null}
                />
              </p>
            </li>
          ))}
        </ol>
        <div ref={endRef} />

        {active ? (
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <label htmlFor="answer" className="sr">Your answer</label>
            <textarea
              id="answer"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
              placeholder="Describe what happened and what you did. Ctrl+Enter to send."
              rows={4}
              disabled={busy}
            />
            <div className="row">
              <button type="submit" className="primary" disabled={busy || !draft.trim()}>
                Send answer
              </button>
              {participantCount >= 2 && (
                <button type="button" className="quiet" disabled={busy} onClick={() => run(() => api.finish(session.id))}>
                  End interview
                </button>
              )}
            </div>
          </form>
        ) : !scored ? (
          <div className="composer">
            <p className="meta">Interview complete. Scoring compares your answers with the framework.</p>
            <button className="primary" disabled={busy} onClick={() => run(() => api.score(session.id))}>
              {busy ? "Scoring…" : "Score interview"}
            </button>
          </div>
        ) : (
          <div className="composer">
            <button className="quiet" onClick={() => { setSession(null); setFocus(null); }}>
              Start a new interview
            </button>
          </div>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {scored && fw && (
        <aside className="results" aria-label="Scored signals">
          <h2>Signals</h2>
          <p className="meta">Select a quote to find it in the transcript.</p>
          {session.signals.map((s) => {
            const dim = fw.dimensions.find((d) => d.key === s.dimension)!;
            return <SignalCard key={s.dimension} signal={s} label={dim.label} definition={dim.definition}
                               anchors={dim.anchors} onFocus={(e) =>
                                 setFocus(e.turn_index == null ? null : { turn: e.turn_index, start: e.start!, end: e.end! })} />;
          })}
          <p className="fine">
            Scores are 0 to 4 against the anchors shown. Quotes that could not be found verbatim in your
            answers are discarded before scoring. Scored by: {cfg?.scorer ?? "unknown"}.
          </p>
        </aside>
      )}
    </div>
  );
}

function Highlighted({ text, spans, focus }: { text: string; spans: Evidence[]; focus: Focus }) {
  if (!spans.length) return <>{text}</>;
  const sorted = [...spans].sort((a, b) => a.start! - b.start!);
  const parts: ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((e, i) => {
    if (e.start! < cursor) return; // skip overlaps
    parts.push(text.slice(cursor, e.start!));
    const isFocus = focus && focus.start === e.start;
    parts.push(
      <mark key={i} className={isFocus ? "focus" : ""} ref={(el) => { if (isFocus && el) el.scrollIntoView({ block: "center", behavior: "smooth" }); }}>
        {text.slice(e.start!, e.end!)}
      </mark>
    );
    cursor = e.end!;
  });
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

function SignalCard(props: {
  signal: Signal; label: string; definition: string; anchors: Record<string, string>;
  onFocus: (e: Evidence) => void;
}) {
  const { signal: s } = props;
  const abstained = s.status === "insufficient_evidence";
  return (
    <article className={`signal ${abstained ? "abstained" : ""}`}>
      <div className="signal-head">
        <h3>{props.label}</h3>
        {abstained ? (
          <span className="badge">Not enough evidence</span>
        ) : (
          <span className="score" aria-label={`Score ${s.score} out of 4`}>
            {[0, 1, 2, 3, 4].map((n) => (
              <i key={n} className={n === s.score ? "on" : ""}>{n}</i>
            ))}
          </span>
        )}
      </div>
      <p className="def">{props.definition}</p>
      {!abstained && (
        <p className="anchor">
          {s.score != null && props.anchors[String(s.score)] ? props.anchors[String(s.score)] : null}
        </p>
      )}
      {s.rationale && <p className="why">{s.rationale}</p>}
      {s.evidence.map((e, i) => (
        <button key={i} className="quote" onClick={() => props.onFocus(e)}>
          {e.quote}
        </button>
      ))}
      {s.dropped_quotes > 0 && (
        <p className="fine">{s.dropped_quotes} proposed quote(s) discarded: not found in your answers.</p>
      )}
    </article>
  );
}
