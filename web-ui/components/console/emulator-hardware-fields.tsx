"use client";
import { hardwareCopy, hardwareStorageCopy } from "../../lib/emulator-hardware-copy";
import { hardwarePresets, sameHardware, type AppliedEmulatorHardware, type EmulatorHardware } from "../../lib/emulator-hardware";
import { useLocale } from "../../lib/i18n";

export function HardwareSummary({ hardware, applied=false }: { hardware: EmulatorHardware | AppliedEmulatorHardware; applied?:boolean }) {
  const { locale } = useLocale();
  const copy=hardwareStorageCopy[locale], format=new Intl.NumberFormat(locale,{maximumFractionDigits:2});
  const capacity="storage_capacity_bytes" in hardware?hardware.storage_capacity_bytes:null;
  const storage=applied
    ? typeof capacity==="number" && Number.isFinite(capacity) && capacity>0 ? `${copy.observed} : ${format.format(capacity/1073741824)} GiB` : copy.unknown
    : "storage_gb" in hardware ? `${copy.initial} : ${hardware.storage_gb} GiB` : copy.unknown;
  return <bdi>{hardware.width} × {hardware.height} · {hardware.density} dpi · {format.format(hardware.ram_mb / 1024)} GiB RAM · {hardware.cpu_cores} CPU · {storage}</bdi>;
}

export function EmulatorHardwareFields({ value, onChange, disabled = false, storageEditable = true }: {
  value: EmulatorHardware; onChange: (value: EmulatorHardware) => void; disabled?: boolean; storageEditable?: boolean;
}) {
  const { locale } = useLocale(), copy = hardwareCopy[locale];
  const selected = Object.entries(hardwarePresets).find(([, hardware]) => sameHardware({ ...hardware, storage_gb: storageEditable ? hardware.storage_gb : value.storage_gb }, value))?.[0] ?? "custom";
  return <fieldset className="emulator-hardware" disabled={disabled}>
    <legend>{copy.heading}</legend><p className="small-copy">{copy.hint}</p>
    <label>{copy.preset}<select value={selected} onChange={event => { const preset = hardwarePresets[event.target.value as keyof typeof hardwarePresets]; if (preset) onChange({ ...preset, storage_gb: storageEditable ? preset.storage_gb : value.storage_gb }); }}>
      <option value="compact">{copy.compact}</option><option value="balanced">{copy.balanced}</option><option value="tablet">{copy.tablet}</option><option value="custom" disabled>{copy.custom}</option>
    </select></label><p className="emulator-hardware-summary"><HardwareSummary hardware={value} /></p>
    <details><summary>{copy.advanced}</summary><p className="small-copy">{copy.bounds}</p><div className="emulator-hardware-grid">
      {([
        ["width", copy.width, 320, 2560, 8], ["height", copy.height, 320, 3200, 8],
        ["density", copy.density, 120, 640, 1], ["ram_mb", copy.ram, 1024, 8192, 256],
        ["cpu_cores", copy.cpu, 1, 8, 1], ["storage_gb", `${hardwareStorageCopy[locale].initial} (GiB)`, 2, 64, 1],
      ] as const).map(([key, label, min, max, step]) => <label key={key}>{label}<input type="number" required min={min} max={max} step={step} value={value[key]} disabled={key === "storage_gb" && !storageEditable} onChange={event => onChange({ ...value, [key]: Number(event.target.value) })} /></label>)}
    </div>{!storageEditable && <p className="small-copy">{copy.locked}</p>}</details>
  </fieldset>;
}
