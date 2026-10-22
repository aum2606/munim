import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  knowledgeApi,
  type ImportPreview,
  type KnowledgeGap,
} from "../api/knowledge";
import { Button } from "../components/ui/button";
import { knowledge as t } from "../i18n/knowledge";

function GapCard({ gap }: { gap: KnowledgeGap }) {
  const cache = useQueryClient();
  const mutation = useMutation({
    mutationFn: (answer: string) => knowledgeApi.answerGap(gap.id, answer),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["knowledge-gaps"] });
      void cache.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  return (
    <article className="gap">
      <p>
        <strong>{gap.question}</strong>
      </p>
      <small>{t.occurrences(gap.occurrences)}</small>
      {gap.status === "open" ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate(
              String(new FormData(event.currentTarget).get("answer")),
            );
          }}
        >
          <label>
            {t.answer}
            <textarea name="answer" required maxLength={2000} />
          </label>
          <Button disabled={mutation.isPending}>{t.answerGap}</Button>
          {mutation.isError && <p role="alert">{t.error}</p>}
        </form>
      ) : (
        <p className="badge">{t.answered}</p>
      )}
    </article>
  );
}
export function KnowledgePage() {
  const cache = useQueryClient();
  const [importId, setImportId] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: knowledgeApi.tenant,
  });
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: knowledgeApi.catalog,
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: knowledgeApi.documents,
    refetchInterval: (query) =>
      query.state.data?.some(
        (document) =>
          document.status === "pending" || document.status === "processing",
      )
        ? 2000
        : false,
  });
  const gaps = useQuery({
    queryKey: ["knowledge-gaps"],
    queryFn: knowledgeApi.gaps,
  });
  const preview = useQuery<ImportPreview>({
    queryKey: ["catalog-import", importId],
    queryFn: async () => {
      throw new Error("No import selected");
    },
    enabled: false,
  });
  const savePreview = (value: ImportPreview) => {
    setImportId(value.id);
    setMapping(value.mapping);
    cache.setQueryData(["catalog-import", value.id], value);
  };
  const upload = useMutation({
    mutationFn: knowledgeApi.import,
    onSuccess: savePreview,
  });
  const remap = useMutation({
    mutationFn: () => knowledgeApi.preview(importId!, mapping),
    onSuccess: savePreview,
  });
  const commit = useMutation({
    mutationFn: () => knowledgeApi.commit(importId!, mapping),
    onSuccess: (value) => {
      savePreview(value);
      void cache.invalidateQueries({ queryKey: ["catalog"] });
    },
  });
  const uploadDocument = useMutation({
    mutationFn: knowledgeApi.upload,
    onSuccess: () => cache.invalidateQueries({ queryKey: ["documents"] }),
  });
  const retry = useMutation({
    mutationFn: knowledgeApi.retry,
    onSuccess: () => cache.invalidateQueries({ queryKey: ["documents"] }),
  });
  const faq = useMutation({
    mutationFn: (form: FormData) =>
      knowledgeApi.faq(
        String(form.get("question")),
        String(form.get("answer")),
      ),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["documents"] }),
  });
  const download = useMutation({
    mutationFn: knowledgeApi.template,
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "munim-catalogue.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  function saveFAQ(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    faq.mutate(new FormData(event.currentTarget));
    event.currentTarget.reset();
  }
  const hasError =
    catalog.isError ||
    documents.isError ||
    gaps.isError ||
    upload.isError ||
    remap.isError ||
    commit.isError ||
    uploadDocument.isError ||
    faq.isError ||
    download.isError ||
    retry.isError;
  return (
    <div className="page-stack">
      <div>
        <p className="eyebrow">{tenant.data?.name}</p>
        <h1>{t.title}</h1>
        <p>{t.intro}</p>
      </div>
      {hasError && <p role="alert">{t.error}</p>}
      <section className="panel">
        <h2>{t.catalogue}</h2>
        <div className="actions">
          <Button
            variant="outline"
            onClick={() => download.mutate()}
            disabled={download.isPending}
          >
            {t.template}
          </Button>
          <label className="file-control">
            {t.uploadCatalogue}
            <input
              type="file"
              accept=".csv,.xlsx"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) upload.mutate(file);
              }}
              disabled={upload.isPending}
            />
          </label>
        </div>
        {preview.data && (
          <div className="import-preview">
            <h3>{preview.data.committed ? t.imported : t.preview}</h3>
            {!preview.data.committed && (
              <>
                <fieldset>
                  <legend>{t.mapping}</legend>
                  <div className="mapping-grid">
                    {Object.keys(t.fields).map((field) => (
                      <label key={field}>
                        {t.fields[field]}
                        <select
                          aria-label={t.fields[field] + " column"}
                          value={mapping[field] || ""}
                          onChange={(event) =>
                            setMapping((current) => {
                              const changed = { ...current };
                              if (event.target.value)
                                changed[field] = event.target.value;
                              else delete changed[field];
                              return changed;
                            })
                          }
                        >
                          <option value="">{t.unmapped}</option>
                          {preview.data?.headers.map((header) => (
                            <option key={header} value={header}>
                              {header}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div className="actions">
                  <Button
                    variant="outline"
                    onClick={() => remap.mutate()}
                    disabled={remap.isPending}
                  >
                    {t.refresh}
                  </Button>
                  <Button
                    onClick={() => commit.mutate()}
                    disabled={
                      commit.isPending ||
                      JSON.stringify(mapping) !==
                        JSON.stringify(preview.data.mapping) ||
                      preview.data.rows.some((row) => row.errors.length > 0)
                    }
                  >
                    {t.commit}
                  </Button>
                </div>
              </>
            )}
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t.row}</th>
                    <th>{t.sku}</th>
                    <th>{t.name}</th>
                    <th>{t.price}</th>
                    <th>{t.status}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.rows.map((row) => (
                    <tr key={row.number}>
                      <td>{row.number}</td>
                      <td>{row.catalog?.sku}</td>
                      <td>{row.catalog?.name}</td>
                      <td>{row.display_price}</td>
                      <td>{row.errors.join("; ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {catalog.isPending ? (
          <p>{t.loading}</p>
        ) : !catalog.data?.length ? (
          <p className="muted">{t.emptyCatalogue}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t.sku}</th>
                  <th>{t.name}</th>
                  <th>{t.price}</th>
                  <th>{t.unit}</th>
                  <th>{t.gst}</th>
                </tr>
              </thead>
              <tbody>
                {catalog.data.map((item) => (
                  <tr key={item.id}>
                    <td>{item.sku}</td>
                    <td>{item.name}</td>
                    <td>{item.display_price}</td>
                    <td>{item.unit}</td>
                    <td>{item.gst_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <h2>{t.documents}</h2>
        <label className="file-control">
          {t.documentUpload}
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) uploadDocument.mutate(file);
            }}
            disabled={uploadDocument.isPending}
          />
        </label>
        <ul className="document-list">
          {documents.data?.map((document) => (
            <li key={document.id}>
              <div>
                <strong>{document.title}</strong>
                <span className="badge">{document.status}</span>
                {document.error && <p role="alert">{document.error}</p>}
              </div>
              {document.status === "failed" && (
                <Button
                  variant="outline"
                  onClick={() => retry.mutate(document.id)}
                >
                  {t.retry}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {!documents.data?.length && <p className="muted">{t.emptyDocuments}</p>}
        <form onSubmit={saveFAQ} className="faq-form">
          <p className="muted">{t.faqHint}</p>
          <label>
            {t.question}
            <input name="question" required maxLength={300} />
          </label>
          <label>
            {t.answer}
            <textarea name="answer" required maxLength={2000} />
          </label>
          <Button disabled={faq.isPending}>{t.saveFAQ}</Button>
        </form>
      </section>
      <section className="panel">
        <h2>{t.gaps}</h2>
        {!gaps.data?.length && <p className="muted">{t.emptyGaps}</p>}
        {gaps.data?.map((gap) => (
          <GapCard key={gap.id} gap={gap} />
        ))}
      </section>
      {tenant.data && (
        <section className="panel">
          <h2>{t.installation}</h2>
          <p>{t.snippet}</p>
          <pre className="snippet">
            <code>{`<script src="${tenant.data.widget_script_url}" data-key="${tenant.data.widget_public_key}" data-api="${tenant.data.public_api_url}" defer></script>`}</code>
          </pre>
        </section>
      )}
    </div>
  );
}
