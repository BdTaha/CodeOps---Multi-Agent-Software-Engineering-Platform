import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { configureTransport } from './transport';
import { environment } from './environment';
import './design/tokens.css';
import './styles.css';
import './product.css';
import './engineering/engineering.css';
import './engineering/teams-resources.css';
import './design/surfaces.css';
import './design/workspace.css';

declare const __CODEOPS_SHOWCASE__: boolean;
if (__CODEOPS_SHOWCASE__) {
  const { createShowcaseApi } = await import('./showcase/showcaseApi');
  configureTransport(createShowcaseApi());
  environment.showcase = true;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
