/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
const {override, addDecoratorsLegacy, addLessLoader} = require('customize-cra');

module.exports = override(
  addDecoratorsLegacy(),
  addLessLoader({
    lessOptions: {
      javascriptEnabled: true,
      modifyVars: {
        '@primary-color': '#28786f',
        '@primary-5': '#318176',
        '@primary-7': '#1e5f58',
        '@link-color': '#28786f',
        '@link-hover-color': '#318176',
        '@link-active-color': '#1e5f58',
        '@success-color': '#39834a',
        '@warning-color': '#ad741f',
        '@error-color': '#c34848',
        '@info-color': '#397fa5',
        '@text-color': '#30363d',
        '@text-color-secondary': '#667078',
        '@disabled-color': '#858b91',
        '@disabled-bg': '#f0f2f3',
        '@border-color-base': '#cdd2d6',
        '@border-color-split': '#e4e7e9',
        '@border-radius-base': '4px',
        '@btn-primary-shadow': 'none',
        '@btn-text-shadow': 'none',
        '@body-background': '#f3f4f5',
        '@layout-body-background': '#f3f4f5',
        '@layout-header-background': '#272b30',
        '@layout-sider-background': '#272b30',
        '@menu-dark-bg': '#272b30',
        '@menu-dark-inline-submenu-bg': '#22262b',
        '@menu-dark-color': '#c2c7cc',
        '@menu-dark-item-hover-bg': '#353b40',
        '@menu-dark-item-active-bg': '#344b47',
        '@menu-dark-selected-item-icon-color': '#d7eee7',
        '@menu-dark-selected-item-text-color': '#d7eee7',
        '@item-active-bg': '#e8f2ef',
        '@item-hover-bg': '#f0f4f3',
        '@table-header-bg': '#f6f7f8',
        '@table-row-hover-bg': '#f3f7f5',
        '@table-selected-row-bg': '#e8f2ef',
        '@table-selected-row-hover-bg': '#deebe6'
      }
    }
  }),
);
