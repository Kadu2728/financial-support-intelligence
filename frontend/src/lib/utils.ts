import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Concatena classes resolvendo conflitos do Tailwind.
 *
 * `clsx` monta a lista (aceitando condicionais); `twMerge` garante que a ultima
 * classe conflitante vence — sem ele, `cn("p-2", "p-4")` deixaria as duas no DOM e
 * o resultado dependeria da ordem no CSS gerado.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
