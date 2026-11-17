import type { NaturalCard } from "./console-types";

export const MAX_RECIPE_CARDS = 14;
export const MAX_CARD_TEXT = 1500;
export const MAX_CARD_CONTEXT = 21_000;

export function normalizeRecipeCards(cards: NaturalCard[]): NaturalCard[] {
  return cards.map(({ id, instruction, verification }) => ({
    id, instruction: instruction.trim(), verification: verification?.trim() || null
  }));
}

export function recipeCardSlots(cards: NaturalCard[]): NaturalCard[] {
  return cards.length === 1 && !cards[0].instruction.trim() && !cards[0].verification?.trim() ? [] : cards;
}

export function recipeCardTextLength(cards: NaturalCard[]): number {
  return cards.reduce((total, card) => total + Array.from(card.instruction).length + Array.from(card.verification ?? "").length, 0);
}
