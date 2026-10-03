import { useCallback, useEffect, useState } from 'react';
import { parseRoute, routeHash } from '../model/route';
import type { Route } from '../model/route';

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const navigate = useCallback((next: Route, replace = false) => {
    const hash = routeHash(next);
    if (replace) window.history.replaceState(null, '', hash);
    else if (hash !== window.location.hash) window.location.hash = hash;
    setRoute(next);
  }, []);
  return { route, navigate };
}
