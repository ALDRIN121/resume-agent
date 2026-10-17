import React from "react";
import { Input, Textarea } from "./components.jsx";

const WORK_MODES = ["Remote", "Hybrid", "On-site"];

export function WorkPreferencesFields({ value = {}, onChange }) {
  const modes = value.work_modes || [];
  return <div className="work-preferences-fields">
    <label className="work-field">
      <span>Preferred locations</span>
      <Textarea aria-label="Preferred locations" value={(value.preferred_locations || []).join("\n")}
        onChange={event => onChange({ ...value, preferred_locations: event.target.value.split("\n") })}
        placeholder={"One location per line, e.g.\nBengaluru, India\nLondon, UK"} style={{ minHeight: 94 }}/>
      <small>Add cities, countries, or regions. Keep your current location in your profile.</small>
    </label>
    <fieldset className="work-mode-options">
      <legend>Preferred work modes</legend>
      <div>{WORK_MODES.map(mode => <label key={mode} className={modes.includes(mode) ? "is-selected" : ""}>
        <input type="checkbox" checked={modes.includes(mode)} onChange={event => onChange({
          ...value, work_modes: event.target.checked ? WORK_MODES.filter(item => item === mode || modes.includes(item)) : modes.filter(item => item !== mode),
        })}/>{mode}
      </label>)}</div>
      <p>Choose every mode you’re open to. Leaving these blank means no preference has been set.</p>
    </fieldset>
  </div>;
}

export function JobContextFields({ location, mode, onLocationChange, onModeChange }) {
  return <section className="job-context-fields" aria-label="Job location and work mode">
    <h3>Location and work mode</h3>
    <p>Optional. Leave these blank to use what’s stated in the posting.</p>
    <div className="form-grid">
      <label className="work-field"><span>Job location</span><Input aria-label="Job location" value={location}
        onChange={event => onLocationChange(event.target.value)} placeholder="City, country, or region"/></label>
      <label className="work-field"><span>Work mode</span><select aria-label="Work mode" value={mode} onChange={event => onModeChange(event.target.value)}>
        <option value="">Use the posting</option>{WORK_MODES.map(mode => <option key={mode} value={mode}>{mode}</option>)}
      </select></label>
    </div>
    <small>Remote roles may still have location or time-zone restrictions.</small>
  </section>;
}

export function JobContextLine({ location, mode }) {
  if (!location && !mode) return null;
  return <div className="job-context-line" aria-label="Job location and work mode">
    {[location, mode].filter(Boolean).join(" · ")}
  </div>;
}

export function WorkContextSummary({ location, mode, policy, preferences }) {
  const selectedModes = preferences?.work_modes || [];
  const knownMode = WORK_MODES.find(item => (mode || "").toLowerCase().startsWith(item.toLowerCase()));
  const modeConflict = knownMode && selectedModes.length > 0 && !selectedModes.includes(knownMode);
  return <section className="work-context-summary" aria-label="Location and work mode">
    <h3>Location and work mode</h3>
    <dl>
      <div><dt>Job location</dt><dd>{location || "Not specified"}</dd></div>
      <div><dt>Work mode</dt><dd>{mode || "Not specified"}</dd></div>
      {policy && policy !== mode && <div><dt>Posting’s work policy</dt><dd>{policy}</dd></div>}
      <div><dt>Your preferred locations</dt><dd>{preferences ? preferences.preferred_locations?.join("; ") || "No preference set" : "Not saved for this run"}</dd></div>
      <div><dt>Your preferred work modes</dt><dd>{preferences ? selectedModes.join(", ") || "No preference set" : "Not saved for this run"}</dd></div>
    </dl>
    {modeConflict && <p className="work-context-conflict">This job’s work mode differs from your saved preferences. Review the requirement before applying.</p>}
  </section>;
}
