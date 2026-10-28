import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { pilotApi, type Erasure } from "../api/pilot";
import { Button } from "../components/ui/button";
import { pt } from "../i18n/pilot";
export function PrivacyPage() {
  const cache = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [result, setResult] = useState<Erasure | null>(null);
  const customers = useQuery({
    queryKey: ["privacy-customers", search],
    queryFn: () => pilotApi.customers(search),
    enabled: me.data?.role === "owner",
  });
  const erase = useMutation({
    mutationFn: () => pilotApi.erase(selected),
    onSuccess: (value) => {
      setResult(value);
      setSelected("");
      setReviewed(false);
      cache.removeQueries({ queryKey: ["conversation-messages"] });
      cache.removeQueries({ queryKey: ["traces"] });
      void cache.invalidateQueries();
    },
  });
  const retry = useMutation({
    mutationFn: () => pilotApi.retry(result!.id),
    onSuccess: setResult,
  });
  if (me.isPending) return <p>{pt.loading}</p>;
  if (me.data?.role !== "owner") return <p>{pt.ownerOnly}</p>;
  return (
    <section className="card">
      <h1>{pt.privacy}</h1>
      <p>{pt.privacyIntro}</p>
      <p>{pt.warning}</p>
      <label>
        {pt.search}
        <input
          value={search}
          maxLength={200}
          onChange={(event) => {
            setSearch(event.target.value);
            setSelected("");
            setReviewed(false);
          }}
        />
      </label>
      {customers.data?.length === 0 && <p>{pt.noCustomers}</p>}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (reviewed && selected) erase.mutate();
        }}
      >
        <label>
          {pt.choose}
          <select
            required
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value);
              setReviewed(false);
            }}
          >
            <option value="">—</option>
            {customers.data?.map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.name ||
                  customer.phone ||
                  customer.email ||
                  `${pt.anonymous} ${customer.id.slice(0, 8)}`}
              </option>
            ))}
          </select>
        </label>
        <label className="consent-check">
          <input
            type="checkbox"
            checked={reviewed}
            onChange={(event) => setReviewed(event.target.checked)}
          />
          {pt.review}
        </label>
        <Button disabled={!reviewed || !selected || erase.isPending}>
          {erase.isPending ? pt.erasing : pt.erase}
        </Button>
      </form>
      {(erase.isError || retry.isError || customers.isError) && (
        <p role="alert">{pt.error}</p>
      )}
      {result && (
        <p role="status">
          {result.status === "complete" ? pt.erased : pt.pending}
        </p>
      )}
      {result?.status === "pending_files" && (
        <Button disabled={retry.isPending} onClick={() => retry.mutate()}>
          {pt.retry}
        </Button>
      )}
    </section>
  );
}
