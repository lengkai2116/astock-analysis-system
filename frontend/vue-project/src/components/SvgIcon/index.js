export default {
  version: '5.0.0',
  install (vue) {
    vue.component('svg-icon', {
      props: {
        icon: {
          type: String,
          required: true
        },
        size: {
          type: [Number, String],
          default: 16
        }
      },
      template: `<svg :width="size" :height="size" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
        <use :xlink:href="'#icon-' + icon"></use>
      </svg>`
    })
  }
}
