import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalyticsResult, ChartSpec } from "../api/insights";
import { it } from "../i18n/insights";
import { Link } from "react-router-dom";

export function AnalyticsTable({ result }: { result: AnalyticsResult }) {
  if (!result.rows.length) return <p>{it.empty}</p>;
  return (
    <div className="analytics-table">
      <table>
        <thead>
          <tr>
            {result.columns.map((column) => (
              <th key={column}>{it.columns[column] ?? column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index}>
              {result.columns.map((column) => {
                const value = row[column];
                const link =
                  typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value)
                    ? column === "conversation_id"
                      ? `/inbox?conversation=${value}`
                      : column === "lead_id"
                        ? `/leads?lead=${value}`
                        : column === "quote_id"
                          ? `/quotes?quote=${value}`
                          : null
                    : null;
                const displayed =
                  typeof value === "string" &&
                  [
                    "last_customer_message",
                    "last_business_message",
                    "lead_created",
                  ].includes(column)
                    ? new Intl.DateTimeFormat("en-IN", {
                        timeZone: "Asia/Kolkata",
                        dateStyle: "medium",
                        timeStyle: "short",
                      }).format(new Date(value.replace(" ", "T")))
                    : String(value ?? "—");
                return (
                  <td key={column}>
                    {link ? (
                      <Link to={link}>
                        {column === "conversation_id"
                          ? it.viewConversation
                          : column === "lead_id"
                            ? it.viewLead
                            : it.viewQuote}
                      </Link>
                    ) : (
                      displayed
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InsightChart({ spec }: { spec: ChartSpec }) {
  if (!spec.rows.length) return <p>{it.empty}</p>;
  // Fixed component/axes only; the server cannot inject JSX, formatter code or arbitrary charts.
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey={spec.x_key} tick={{ fontSize: 11 }} />
      <YAxis allowDecimals={false} width={40} />
      <Tooltip />
    </>
  );
  return (
    <>
      <div className="insight-chart" role="img" aria-label={spec.title}>
        <ResponsiveContainer
          width="100%"
          height={240}
          minWidth={0}
          initialDimension={{ width: 300, height: 240 }}
        >
          {spec.kind === "line" ? (
            <LineChart
              data={spec.rows}
              margin={{ left: 0, right: 16, bottom: 8 }}
            >
              {axes}
              <Line
                type="monotone"
                dataKey={spec.y_key}
                name={it.columns[spec.y_key] ?? spec.y_key}
                stroke="#196a59"
                strokeWidth={2}
                isAnimationActive={false}
              />
            </LineChart>
          ) : (
            <BarChart
              data={spec.rows}
              margin={{ left: 0, right: 16, bottom: 8 }}
            >
              {axes}
              <Bar
                dataKey={spec.y_key}
                name={it.columns[spec.y_key] ?? spec.y_key}
                fill="#196a59"
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <details>
        <summary>{it.table}</summary>
        <AnalyticsTable
          result={{
            columns: [spec.x_key, spec.y_key],
            rows: spec.rows,
            total: spec.rows.length,
            truncated: false,
          }}
        />
      </details>
    </>
  );
}
