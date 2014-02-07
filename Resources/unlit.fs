#version 120

uniform sampler2D tex;
varying vec2 texcoord;

void main()
{
    gl_FragColor = gl_Color * texture2D(tex, texcoord);
}
