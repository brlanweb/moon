import React from 'react';
import styles from './moon-brand.module.css';

export default function MoonBrand({compact = false, className = ''}) {
  return (
    <span className={`${styles.brand} ${className}`}>
      <img src={`${process.env.PUBLIC_URL || ''}/moon-mark.svg`} alt="Moon" width="36" height="36"/>
      {!compact && <span aria-hidden="true">Moon</span>}
    </span>
  );
}
