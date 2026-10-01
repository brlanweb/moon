import {useEffect} from 'react';
import {matchPath, useLocation} from 'react-router-dom';

export function resolvePageTitle(routes, pathname, parentTitle = '') {
  for (const route of routes) {
    const label = route.browserTitle || route.title || parentTitle;
    if (route.child) {
      const found = resolvePageTitle(route.child, pathname, label);
      if (found) return found;
    }
    if (route.path && matchPath(pathname, {path: route.path, exact: true})) {
      return label ? `${label} | Moon` : 'Moon';
    }
  }
  return null;
}

export default function PageTitle({routes}) {
  const {pathname} = useLocation();
  const title = resolvePageTitle(routes, pathname) || 'Moon';
  useEffect(() => { document.title = title; }, [pathname, title]);
  return null;
}
