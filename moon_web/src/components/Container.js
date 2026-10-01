import React from 'react'


function Container(props) {
  const {visible, style, className} = props;

  return (
    <div style={{display: visible ? 'block' : 'none', ...style, maxWidth: '100%'}} className={className}>
      {props.children}
    </div>
  )
}

Container.defaultProps = {
  visible: true
}

export default Container
