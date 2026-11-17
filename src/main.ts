import './styles.css';
import { renderApp } from './app';

renderApp();
window.addEventListener('hashchange', renderApp);
