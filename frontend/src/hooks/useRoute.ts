import { useCallback, useEffect, useRef, useState } from 'react';
import { parseRoute, routeHash } from '../model/route';
import type { Route } from '../model/route';

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  const sidebar = useRef(route.sidebar);
  const retainSidebar = useCallback((next: Route) => {
    if (next.sidebar) sidebar.current = next.sidebar;
    return sidebar.current ? { ...next, sidebar: sidebar.current } : next;
  }, []);
  useEffect(() => {
    const update = () => {
      const next = retainSidebar(parseRoute(window.location.hash));
      const hash = routeHash(next);
      if (hash !== window.location.hash) window.history.replaceState(null, '', hash);
      setRoute(next);
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, [retainSidebar]);
  const navigate = useCallback(
    (input: Route, replace = false) => {
      const next = retainSidebar(input);
      const hash = routeHash(next);
      if (replace) window.history.replaceState(null, '', hash);
      else if (hash !== window.location.hash) window.location.hash = hash;
      setRoute(next);
    },
    [retainSidebar],
  );
  return { route, navigate };
}
