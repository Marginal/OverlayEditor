#version 120

void main()
{
    float r = dot(gl_PointCoord-0.5,gl_PointCoord-0.5);	// radius within dot [0,0.25]
    gl_FragColor = gl_Color;
    gl_FragColor.a = gl_FragColor.a * smoothstep(0.2, 0.3, 0.5 - r);
}
