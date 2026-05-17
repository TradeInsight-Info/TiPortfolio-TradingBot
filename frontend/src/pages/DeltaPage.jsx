import DeltaTable from "../components/DeltaTable";

export default function DeltaPage() {
  return (
    <main className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Trade Records</h1>
      <p className="text-gray-500 mb-6">
        All rebalance decisions made by the algorithm, sorted by most recent first.
      </p>
      <div className="m-auto">
        <DeltaTable />
      </div>
    </main>
  );
}
