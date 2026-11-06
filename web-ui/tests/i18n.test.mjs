import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { collectUISources } from '../scripts/i18n-sources.mjs';
import { detectLocale, direction, formatDate, interpolate, translateSource, localeInfo, locales, normalizeLocale } from '../lib/i18n-core.ts';

test('locale detection honors choice, weighted browser preferences and region aliases', () => {
  assert.equal(detectLocale('de', 'fr-FR, en;q=0.8'), 'de');
  assert.equal(detectLocale(null, 'xx-ZZ, hi-IN;q=0.8, fr;q=0.2'), 'hi');
  assert.equal(detectLocale('', 'fr;q=0, en;q=0.8, de;q=0.9'), 'de');
  assert.equal(detectLocale('invalid', 'zh-Hant-TW, en;q=0.1'), 'zh');
  assert.equal(detectLocale(null, 'pt-BR'), 'pt');
  assert.equal(detectLocale(null, 'fr;q=no, de;q=2, en;q=-1'), 'en');
  assert.equal(detectLocale(null, ''), 'en');
  assert.equal(detectLocale(null, 'fr;q=0.8,de;q=0.8'), 'fr');
  assert.equal(normalizeLocale('AR_sa'), 'ar');
  assert.equal(detectLocale(null, 'fr;Q=0,en;q=0.8'), 'en');
  assert.equal(normalizeLocale('../../fr'), null);
});
test('direction and each locale provide supported formatting and local flag assets', () => {
  for (const locale of locales) {
    assert.equal(direction(locale), locale === 'ar' ? 'rtl' : 'ltr');
    assert.ok(Intl.DateTimeFormat.supportedLocalesOf([localeInfo[locale].intl]).length);
    const flag = readFileSync(new URL(`../public/flags/${localeInfo[locale].flag}.svg`, import.meta.url), 'utf8');
    assert.ok(flag.startsWith('<svg'));
    assert.doesNotMatch(flag, /<script|<foreignObject|https?:\/\/(?!www.w3.org)/);
  }
});
test('translation interpolation preserves unknown keys and treats values as literal data', () => {
  assert.equal(interpolate('{count} devices for {name}', { count: 3, name: '$&<script>' }), '3 devices for $&<script>');
  assert.equal(interpolate('{missing} {constructor} {count}', { count: 0 }), '{missing} {constructor} 0');
});
test('all ten static catalogs cover exactly the same labels and preserve placeholders', () => {
  const source = JSON.parse(readFileSync(new URL('../lib/locales/fr.json', import.meta.url), 'utf8'));
  const expected = Object.keys(source).sort();
  assert.ok(expected.length > 100, 'real UI copy is included');
  for (const key of collectUISources()) assert.ok(Object.hasOwn(source, key), `UI source missing from catalogs: ${key}`);
  for (const locale of locales) {
    const catalog = JSON.parse(readFileSync(new URL(`../lib/locales/${locale}.json`, import.meta.url), 'utf8'));
    assert.deepEqual(Object.keys(catalog).sort(), expected, locale);
    for (const key of expected) {
      assert.equal(typeof catalog[key], 'string', `${locale}: ${key}`);
      assert.ok(catalog[key].trim(), `${locale}: ${key}`);
      assert.deepEqual((catalog[key].match(/\{\w+\}/g) ?? []).sort(), (key.match(/\{\w+\}/g) ?? []).sort(), `${locale}: ${key}`);
    }
  }
});

test('automation run terminology never uses capital-punishment wording', () => {
  const forbidden = { zh: /处决|死刑/, ar: /الإعدام/, hi: /फांसी/, bn: /মৃত্যুদণ্ড/, de: /Hinrichtung/i, ru: /казн/i };
  for (const [locale, pattern] of Object.entries(forbidden)) {
    const catalog = JSON.parse(readFileSync(new URL(`../lib/locales/${locale}.json`, import.meta.url), 'utf8'));
    for (const [source, text] of Object.entries(catalog)) assert.doesNotMatch(text, pattern, `${locale}: ${source}`);
  }
});


test('workflow names matching object prototype properties remain safe literal labels', () => {
  const catalog = { "Bonjour {name}": "Hello {name}" };
  for (const source of ["constructor", "toString", "__proto__", "valueOf", "hasOwnProperty"])
    assert.equal(translateSource(catalog, source), source);
  assert.equal(translateSource(catalog, "Bonjour {name}", { name: "Camille" }), "Hello Camille");
  assert.equal(translateSource(JSON.parse('{"constructor":"Custom label"}'), "constructor"), "Custom label");
});
test('schedule timestamps use their stored timezone, independently of the browser timezone', () => {
  const winter = "2026-11-07T08:00:00Z";
  assert.match(formatDate(winter, "en", "Europe/Paris"), /09:00/);
  assert.match(formatDate(winter, "en", "America/New_York"), /03:00/);
  const summer = "2026-07-07T08:00:00Z";
  assert.match(formatDate(summer, "en", "Europe/Paris"), /10:00/);
  assert.match(formatDate(summer, "en", "America/New_York"), /04:00/);
});
