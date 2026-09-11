"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatarTamanho } from "@/features/documents/types";

/**
 * Envio de documento.
 *
 * As mensagens de erro sao escolhidas por `code`, o contrato estavel do backend. Cada
 * uma diz o que aconteceu E o que fazer — "formato nao suportado" sozinho deixa o
 * administrador sem saber quais formatos existem.
 */
const MENSAGENS: Record<string, string> = {
  UNSUPPORTED_FILE_TYPE: "Formato nao suportado. Envie PDF, DOCX, Markdown ou texto.",
  FILE_TOO_LARGE: "Arquivo grande demais. O limite e 25 MB.",
  DUPLICATE_DOCUMENT: "Este arquivo ja esta no acervo. Verifique a lista antes de reenviar.",
  VALIDATION_ERROR: "Confira os campos: o titulo precisa ter ao menos 3 caracteres.",
  FORBIDDEN: "Apenas administradores podem enviar documentos.",
  UPSTREAM_UNAVAILABLE: "O armazenamento esta indisponivel. Tente novamente em instantes.",
};

const PADRAO = "Nao foi possivel enviar o documento. Tente novamente.";

// Aceita apenas o que o backend sabe extrair. O atributo `accept` e conveniencia de
// UI, nao validacao — quem decide e a assinatura do arquivo, no servidor.
const FORMATOS = ".pdf,.docx,.md,.markdown,.txt";

export function UploadDialog({ onEnviado }: { onEnviado?: () => void }) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);

  const [aberto, setAberto] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [arquivo, setArquivo] = useState<File | null>(null);

  function fechar() {
    setAberto(false);
    setErro(null);
    setArquivo(null);
    formRef.current?.reset();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErro(null);
    setEnviando(true);

    try {
      const resposta = await fetch("/api/backend/documents", {
        method: "POST",
        // FormData sem Content-Type manual: o navegador precisa gerar o boundary.
        body: new FormData(event.currentTarget),
      });

      if (!resposta.ok) {
        const corpo = await resposta.json().catch(() => null);
        const codigo = corpo?.error?.code as string | undefined;
        setErro((codigo && MENSAGENS[codigo]) ?? PADRAO);
        return;
      }

      fechar();
      onEnviado?.();
      router.refresh();
    } catch {
      setErro("Falha de conexao. Verifique sua rede e tente novamente.");
    } finally {
      setEnviando(false);
    }
  }

  if (!aberto) {
    return <Button onClick={() => setAberto(true)}>Enviar documento</Button>;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/20 p-4 pt-[10vh]">
      {/* Backdrop clicavel para fechar, com o dialogo parando a propagacao. */}
      <button
        type="button"
        aria-label="Fechar"
        className="fixed inset-0 -z-10 cursor-default"
        onClick={fechar}
        disabled={enviando}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="titulo-envio"
        className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-lg"
      >
        <h2 id="titulo-envio" className="text-base font-semibold tracking-tight">
          Enviar documento
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          O conteudo e indexado em segundo plano. O documento fica disponivel para
          consulta quando o processamento terminar.
        </p>

        <form ref={formRef} onSubmit={onSubmit} className="mt-5 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="title">Titulo</Label>
            <Input
              id="title"
              name="title"
              required
              minLength={3}
              maxLength={512}
              autoFocus
              disabled={enviando}
              placeholder="Manual de Cadastro de Clientes"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="category">
              Categoria <span className="font-normal text-muted-foreground">(opcional)</span>
            </Label>
            <Input
              id="category"
              name="category"
              maxLength={128}
              disabled={enviando}
              placeholder="Cadastro, Pagamentos, Compliance..."
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="description">
              Descricao <span className="font-normal text-muted-foreground">(opcional)</span>
            </Label>
            <Input
              id="description"
              name="description"
              maxLength={2000}
              disabled={enviando}
              placeholder="O que este documento cobre"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="file">Arquivo</Label>
            <Input
              id="file"
              name="file"
              type="file"
              required
              accept={FORMATOS}
              disabled={enviando}
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              className="file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium"
            />
            <p className="text-xs text-muted-foreground">
              {arquivo
                ? `${arquivo.name} — ${formatarTamanho(arquivo.size)}`
                : "PDF, DOCX, Markdown ou texto. Ate 25 MB."}
            </p>
          </div>

          <div aria-live="polite" className="min-h-5">
            {erro ? <p className="text-sm text-destructive">{erro}</p> : null}
          </div>

          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button type="button" variant="outline" onClick={fechar} disabled={enviando}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando}>
              {enviando ? "Enviando..." : "Enviar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
