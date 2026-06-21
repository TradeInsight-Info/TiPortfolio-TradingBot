import { createContext, useContext, useEffect, useState } from "react";
import { useStrategies } from "../hooks/useStrategies";

const Ctx = createContext({ strategyId: null, setStrategyId: () => {}, strategies: [], loading: true, error: null });
export const useStrategy = () => useContext(Ctx);

export function StrategyProvider({ children }) {
  const { strategies, loading, error } = useStrategies();
  const [strategyId, setStrategyId] = useState(null);
  useEffect(() => {
    if (!strategyId && strategies.length) setStrategyId(strategies[0].id);
  }, [strategies, strategyId]);
  return (
    <Ctx.Provider value={{ strategyId, setStrategyId, strategies, loading, error }}>
      {children}
    </Ctx.Provider>
  );
}
